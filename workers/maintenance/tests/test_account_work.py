"""A deleted account's work in the worker: the person gone at the identity
provider, the personal org's subscription canceled and its customer deleted,
its Slack app removed, the org deleted and then purged whole by the sweep,
their place in a team org gone with their account while what they made there
stays, and their open tasks there unassigned; a provider that is down, or
refusing the process's key, parking the work until it answers, and every
other worker's with it; and a provider that refuses the call itself failing
it at once."""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from slack_support import build, install, make_task, on_team, owner_of
from test_billing_work import checkout, consumer_of, queued
from worker_support import build_container, request, signing, start_import, upload

from tadas.infra.base import SYSTEM_SCOPE, utcnow
from tadas.infra.buckets import Buckets
from tadas.infra.cache import CacheScope
from tadas.infra.cache.memory import CacheMemoryImpl
from tadas.infra.outages import Outage
from tadas.infra.outages.cache import OutageSignalCacheImpl
from tadas.integrations.exceptions import (
    PaymentsKeyRefused,
    PaymentsRefused,
    ProviderConflict,
    ProviderRefused,
    ProviderUnavailable,
)
from tadas.integrations.identity.twin import IdentityProviderTwinImpl
from tadas.integrations.payments.twin import PaymentsTwinImpl
from tadas.om.base import new_id
from tadas.om.billing.types.plan import Plan
from tadas.om.context import Role, TenantContext
from tadas.om.media.types.file import File, FilePurpose
from tadas.om.tasks.types.task import TaskStatus
from tadas.om.work.types.handler import WorkParked, WorkRefused
from tadas.om.work.types.work_item import WorkItem, WorkKind
from tadas.workers.maintenance.accounts import DeleteAccountHandlerImpl
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.main import (
    IDENTITY,
    IDENTITY_CREDENTIAL,
    PAYMENTS,
    PAYMENTS_CREDENTIAL,
    build_loop,
)
from tadas.workers.maintenance.providers import PROVIDER_WAIT, ProviderCalls

LEASE = timedelta(seconds=30)
ACCOUNT_WORK = [WorkKind.DELETE_ACCOUNT, WorkKind.UNASSIGN_TASKS, WorkKind.SYNC_SEATS]


def identity_of(container: WorkerContainer) -> IdentityProviderTwinImpl:
    return cast(IdentityProviderTwinImpl, container.identity_provider)


async def bob_signs_in(
    container: WorkerContainer, org_id: UUID
) -> tuple[TenantContext, TenantContext]:
    """Bob, a member of the org, signs in through the provider's twin, which
    then knows him by a subject: his session in the org, and in his personal
    org."""
    tenancy = container.managers.tenancy
    await tenancy.add_member(request(), "ajax", "bob@example.test", "Bob", Role.MEMBER)
    through = signing(container, container.identity_provider)
    places: list[TenantContext] = []
    login = await through.sign_in.sign_in_with_code(
        request(), identity_of(container).issue_code("bob@example.test")
    )
    home = next(m.org.id for m in login.memberships if m.org.personal)
    for target in (org_id, home):
        code = identity_of(container).issue_code("bob@example.test")
        login = await through.sign_in.sign_in_with_code(request(), code)
        identity = await tenancy.authenticate_login(request(), login.token)
        issued = await tenancy.sign_in.exchange_login(identity, target)
        places.append(await tenancy.authenticate(request(), issued.token))
    return places[0], places[1]


async def claim_deletion(container: WorkerContainer) -> tuple[TenantContext, WorkItem]:
    claimed = await container.managers.work.claim(
        request(), "default", [WorkKind.DELETE_ACCOUNT], "test", LEASE
    )
    assert claimed is not None
    return claimed


async def attach(container: WorkerContainer, ctx: TenantContext, task_id: UUID) -> File:
    data = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    now = utcnow()
    file = await container.managers.tasks.attachments.attach_file(
        ctx,
        task_id,
        File(
            id=new_id(),
            name="plan.png",
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            content_type="image/png",
            size_bytes=len(data),
            purpose=FilePurpose.TASK_ATTACHMENT,
        ),
    )
    await container.managers.media.put_content(ctx, file.id, data)
    return await container.managers.media.confirm_file(ctx, file.id)


async def run(container: WorkerContainer) -> list[WorkItem]:
    """Claims every account item and runs it with the worker's own handler,
    settling it as the loop does."""
    handlers = build_loop(container)._handlers  # pyright: ignore[reportPrivateUsage]
    ran: list[WorkItem] = []
    while True:
        claimed = await container.managers.work.claim(
            request(), "default", ACCOUNT_WORK, "test", LEASE
        )
        if claimed is None:
            return ran
        ctx, item = claimed
        await handlers[item.kind].handle(ctx, item)
        await container.managers.work.complete(ctx, item)
        ran.append(item)


async def test_a_deleted_account_leaves_nothing_of_its_person_behind(tmp_path: Path) -> None:
    container, slack = build(tmp_path)
    tasks, tenancy = container.managers.tasks, container.managers.tenancy
    ann = await owner_of(container, "ajax")
    await on_team(container, ann)
    bob, home = await bob_signs_in(container, ann.org_id)
    subject = (await tenancy.org.get_identity(bob)).subject
    assert subject is not None and subject in identity_of(container).users

    # In Ajax, a file Bob stored, a task assigned to him, one he made and left
    # open, one of Ann's, and a done one of his.
    shared = await upload(container, bob, "shared.webm")
    his = await tasks.create_task(bob, make_task(ann, "Ship it", assignee_id=bob.user_id))
    made = await tasks.create_task(bob, make_task(bob, "Bob's idea"))
    anns = await tasks.create_task(ann, make_task(ann, "Ann's", assignee_id=ann.user_id))
    done = await tasks.create_task(bob, make_task(bob, "Done", assignee_id=bob.user_id))
    done = await tasks.update_task(
        bob, done.model_copy(update={"status": TaskStatus.DONE}), done.version
    )
    # At home, a file and a record of his, a task with a file, a paid plan,
    # and the Slack app.
    note = await upload(container, home, "note.webm")
    record = await start_import(container, home, 3)
    groceries = await tasks.create_task(home, make_task(home, "Groceries"))
    attached = await attach(container, home, groceries.id)
    buckets = container.infra.get_buckets()
    assert await buckets.exists(home.org_id, Buckets.USER_FILE_UPLOADS, note.key)
    assert await buckets.exists(home.org_id, Buckets.USER_FILE_UPLOADS, attached.key)
    payload = await checkout(container, home, Plan.PRO, 1)
    assert await consumer_of(container).handle(await queued(container, payload)) == "applied"
    account = (await container.managers.billing.get_billing(home)).account
    assert account is not None and account.customer_id and account.subscription_id
    await install(container, slack, home)
    assert await container.managers.slack.get_installation(home) is not None

    await tenancy.org.delete_account(bob, "bob@example.test")
    ran = await run(container)
    assert {item.kind for item in ran} >= {WorkKind.DELETE_ACCOUNT, WorkKind.UNASSIGN_TASKS}

    # The providers' side is gone.
    assert identity_of(container).deleted == [subject]
    payments = cast(PaymentsTwinImpl, container.payments)
    assert account.customer_id not in payments.customers
    assert payments.subscriptions[account.subscription_id]["status"] == "canceled"
    assert slack.uninstalled, "the app left the workspace"
    # The personal org is deleted, and the sweep purges it whole at its next pass.
    org = await container.storage.get_tenancy_storage().read_org(home.org_id)
    assert org is not None and org.deleted_at is not None
    loop = build_loop(container)
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert not await buckets.exists(home.org_id, Buckets.USER_FILE_UPLOADS, note.key)
    assert not await buckets.exists(home.org_id, Buckets.USER_FILE_UPLOADS, attached.key)
    media = container.storage.get_media_storage()
    assert await media.read_file(home.org_id, note.id) is None
    orchestrations = container.storage.get_orchestrations_storage()
    assert await orchestrations.read_orchestration(home.org_id, record.id) is None
    assert await container.storage.get_tasks_storage().read_task(home.org_id, groceries.id) is None
    assert await container.storage.get_billing_storage().read_account(home.org_id) is None
    assert await container.managers.slack.get_installation(home) is None
    # The next pass finds nothing left, and the sweep leaves the org out.
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    service = await tenancy.service_contexts(request())
    assert home.org_id not in {ctx.org_id for ctx in service}

    # In Ajax his place is gone, and what he made stays, by id: his open task
    # is nobody's now.
    assert (await media.read_file(ann.org_id, shared.id)) is not None
    assert (await container.managers.media.get_file(ann, shared.id)).created_by == bob.user_id
    released = await tasks.get_task(ann, his.id)
    assert released.assignee_id is None and released.updated_by == bob.user_id
    assert (await tasks.get_task(ann, made.id)).created_by == bob.user_id
    assert (await tasks.get_task(ann, anns.id)).assignee_id == ann.user_id
    assert (await tasks.get_task(ann, done.id)).assignee_id == bob.user_id, "only open tasks"
    with pytest.raises(Exception):  # noqa: B017 (no user by that id any more)
        await tenancy.members.get_user(ann, bob.user_id)


async def test_a_provider_that_is_down_parks_the_work_until_it_answers(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ann = await owner_of(container, "ajax")
    bob, home = await bob_signs_in(container, ann.org_id)
    await container.managers.tenancy.org.delete_account(bob, "bob@example.test")
    identity_of(container).unavailable_for = 1
    handlers = build_loop(container)._handlers  # pyright: ignore[reportPrivateUsage]
    ctx, item = await claim_deletion(container)
    with pytest.raises(WorkParked):
        await handlers[item.kind].handle(ctx, item)
    # Nothing failed and nothing moved on: the org waits for the provider.
    org = await container.storage.get_tenancy_storage().read_org(home.org_id)
    assert org is not None and org.deleted_at is None
    await handlers[item.kind].handle(ctx, item)
    assert len(identity_of(container).deleted) == 1
    org = await container.storage.get_tenancy_storage().read_org(home.org_id)
    assert org is not None and org.deleted_at is not None
    # A second run finds every step done.
    await handlers[item.kind].handle(ctx, item)
    assert len(identity_of(container).deleted) == 1


async def test_one_workers_failed_call_parks_the_next_without_a_call_until_one_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two workers on one shared cache. The first one's call fails and marks
    the provider out; the second reads the mark and parks its item until the
    mark's retry time, with no call. A call that answers clears the mark."""
    container = build_container(tmp_path)
    ann = await owner_of(container, "ajax")
    bob, _ = await bob_signs_in(container, ann.org_id)
    await container.managers.tenancy.org.delete_account(bob, "bob@example.test")
    ctx, item = await claim_deletion(container)
    shared = OutageSignalCacheImpl(CacheMemoryImpl(CacheScope.OUTAGE))
    wait = timedelta(milliseconds=200)

    def worker() -> DeleteAccountHandlerImpl:
        calls = ProviderCalls(shared, IDENTITY, IDENTITY_CREDENTIAL, wait=wait)
        payments = ProviderCalls(shared, PAYMENTS, PAYMENTS_CREDENTIAL, wait=wait)
        return DeleteAccountHandlerImpl(
            container.managers.tenancy,
            container.managers.billing,
            container.managers.slack,
            container.identity_provider,
            calls,
            payments,
        )

    first, second = worker(), worker()
    twin = identity_of(container)

    # The first worker's call fails: its item parks, and the pair is marked.
    twin.unavailable_for = 1
    with pytest.raises(WorkParked):
        await first.handle(ctx, item)
    mark = await shared.current(SYSTEM_SCOPE, IDENTITY, IDENTITY_CREDENTIAL)
    assert mark is not None

    # The second reads the mark and parks until its retry time. It makes no
    # call: the provider still holds the failure a call would have taken.
    twin.unavailable_for = 1
    with pytest.raises(WorkParked) as parked:
        await second.handle(ctx, item)
    assert twin.unavailable_for == 1 and twin.deleted == []
    assert timedelta(0) <= parked.value.resume_after <= wait

    # Past the retry time the second calls. Another worker's call fails while
    # this one is in flight and marks the pair again; this one answers, and
    # its success clears the mark.
    twin.unavailable_for = 0
    await asyncio.sleep(max((mark.retry_at - utcnow()).total_seconds(), 0))
    delete = twin.delete_user

    async def answers_while_another_fails(user_id: str) -> None:
        again = Outage(
            org_id=SYSTEM_SCOPE,
            provider=IDENTITY,
            credential=IDENTITY_CREDENTIAL,
            retry_at=utcnow() + PROVIDER_WAIT,
        )
        await shared.mark(again)
        await delete(user_id)

    monkeypatch.setattr(twin, "delete_user", answers_while_another_fails)
    await second.handle(ctx, item)
    assert len(twin.deleted) == 1
    assert await shared.current(SYSTEM_SCOPE, IDENTITY, IDENTITY_CREDENTIAL) is None


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        # What the WorkOS client raises for a 4xx on the request (400, 404
        # past the one that means gone, 422), and for a 5xx or a 401/403 on
        # its own key, which it answers as unavailable.
        (ProviderRefused("deleting the user: bad id"), WorkRefused),
        (ProviderConflict("deleting the user: in the way"), WorkRefused),
        (ProviderUnavailable("deleting the user: WorkOS answered 503"), WorkParked),
        (ProviderUnavailable("deleting the user: WorkOS refused the key (401)"), WorkParked),
    ],
)
async def test_a_refusal_of_the_call_fails_and_one_that_may_pass_parks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    outcome: type[Exception],
) -> None:
    container = build_container(tmp_path)
    ann = await owner_of(container, "ajax")
    bob, home = await bob_signs_in(container, ann.org_id)
    await container.managers.tenancy.org.delete_account(bob, "bob@example.test")
    ctx, item = await claim_deletion(container)

    async def answer(user_id: str) -> None:
        raise error

    monkeypatch.setattr(identity_of(container), "delete_user", answer)
    with pytest.raises(outcome) as raised:
        await build_loop(container)._handlers[item.kind].handle(ctx, item)  # pyright: ignore[reportPrivateUsage]
    assert str(error) in str(raised.value)
    # Either way nothing moved on: the org waits, for the provider or a person.
    org = await container.storage.get_tenancy_storage().read_org(home.org_id)
    assert org is not None and org.deleted_at is None


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (PaymentsRefused("delete customer", "invalid_request_error"), WorkRefused),
        (PaymentsKeyRefused("delete customer", "PermissionError"), WorkParked),
    ],
)
async def test_the_processor_refusing_the_call_fails_it_and_its_key_parks_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    outcome: type[Exception],
) -> None:
    container = build_container(tmp_path)
    ann = await owner_of(container, "ajax")
    bob, home = await bob_signs_in(container, ann.org_id)
    payload = await checkout(container, home, Plan.PRO, 1)
    assert await consumer_of(container).handle(await queued(container, payload)) == "applied"
    await container.managers.tenancy.org.delete_account(bob, "bob@example.test")
    ctx, item = await claim_deletion(container)

    async def answer(customer_id: str) -> None:
        raise error

    monkeypatch.setattr(cast(PaymentsTwinImpl, container.payments), "delete_customer", answer)
    with pytest.raises(outcome):
        await build_loop(container)._handlers[item.kind].handle(ctx, item)  # pyright: ignore[reportPrivateUsage]
    org = await container.storage.get_tenancy_storage().read_org(home.org_id)
    assert org is not None and org.deleted_at is None
