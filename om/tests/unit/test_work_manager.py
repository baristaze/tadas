from datetime import timedelta
from pathlib import Path

import pytest
from contracts.work_storage import make_item

from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.topics import EntityChangedPayload, TopicPayload, Topics, WorkAvailablePayload
from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import DuplicateWorkItem, LeaseLost, NotFound, ValidationFailed
from tadas.om.opcontext import AppContext, AppType, CredentialKind, OpContext, RequestContext, Role
from tadas.om.root import Managers, build_managers
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.work.impl.manager import DEAD_LETTER_KIND, WorkOptions
from tadas.om.work.types.work_item import WorkKind, WorkStatus

LEASE = timedelta(seconds=30)
APP = AppContext(type=AppType.PORTAL, version="portal@test")
WORKER = AppContext(type=AppType.WORKER, version="worker@test")


def request(app: AppContext = WORKER) -> RequestContext:
    """The request stage the worker mints per claim and per sweep pass."""
    return RequestContext(request_id=new_id(), app=app)


@pytest.fixture
def infra(tmp_path: Path) -> InfraLocalImpl:
    return InfraLocalImpl(tmp_path)


@pytest.fixture
def storage() -> StorageMemoryImpl:
    return StorageMemoryImpl()


@pytest.fixture
def managers(infra: InfraLocalImpl, storage: StorageMemoryImpl) -> Managers:
    return build_managers(storage, infra)


@pytest.fixture
async def ctx(managers: Managers) -> OpContext:
    tenancy = managers.tenancy
    _, org = await tenancy.bootstrap(
        request(APP), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    login = await tenancy.login(request(APP), "ann@example.test", "pw-1234")
    identity = await tenancy.authenticate_login(request(APP), login.token)
    issued = await tenancy.exchange_login(identity, org.id)
    return await tenancy.authenticate(request(APP), issued.token)


async def test_enqueue_publishes_and_claim_returns_the_enqueuers_context(
    managers: Managers, infra: InfraLocalImpl, ctx: OpContext
) -> None:
    seen: list[TopicPayload] = []

    async def record(payload: TopicPayload) -> None:
        seen.append(payload)

    infra.get_topics().subscribe(Topics.WORK_AVAILABLE, "test", record)
    item = make_item().model_copy(update={"created_by": ctx.user_id})
    await managers.work.enqueue(ctx, item)
    assert isinstance(seen[0], WorkAvailablePayload)
    assert seen[0].lane == "default" and seen[0].kind == "NOOP"
    assert seen[0].idempotency_key == item.idempotency_key

    claim_request = request()
    claimed = await managers.work.claim(claim_request, "default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    work_ctx, claimed_item = claimed
    assert work_ctx.org_id == ctx.org_id
    assert work_ctx.user_id == ctx.user_id
    assert work_ctx.security.role is Role.SERVICE
    assert work_ctx.security.credential_kind is CredentialKind.INTERNAL
    # The work context refines the request stage the worker minted for the claim.
    assert work_ctx.app.type is AppType.WORKER and work_ctx.request_id == claim_request.request_id
    assert claimed_item.claimed_by == "w1"

    done = await managers.work.complete(work_ctx, claimed_item)
    assert done.status is WorkStatus.DONE and done.claimed_by is None
    assert await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE) is None


async def test_defer_and_release_hand_back_without_spending_an_attempt(
    managers: Managers, ctx: OpContext
) -> None:
    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    claimed = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    deferred = await managers.work.defer(claimed[0], claimed[1], timedelta(hours=1))
    assert deferred.status is WorkStatus.QUEUED and deferred.attempts == 0
    assert deferred.available_at > utcnow() + timedelta(minutes=59)
    assert await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE) is None

    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    reclaimed = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert reclaimed is not None and reclaimed[1].attempts == 1
    released = await managers.work.release(reclaimed[0], reclaimed[1])
    assert released.attempts == 0 and released.status is WorkStatus.QUEUED
    again = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w2", LEASE)
    assert again is not None and again[1].attempts == 1


async def test_fail_requeues_with_a_growing_delay_then_fails(
    managers: Managers, ctx: OpContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = make_item().model_copy(update={"created_by": ctx.user_id, "max_attempts": 2})
    await managers.work.enqueue(ctx, item)
    first = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert first is not None
    requeued = await managers.work.fail(first[0], first[1], "boom")
    assert requeued.status is WorkStatus.QUEUED and requeued.last_error == "boom"
    assert requeued.available_at > utcnow() + timedelta(seconds=20)
    assert await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE) is None

    # Without a delay the requeued item is claimable at once, and the second
    # failure spends the last attempt.
    monkeypatch.setattr(managers.work, "_options", WorkOptions(base_retry_delay=timedelta(0)))
    other = make_item().model_copy(update={"created_by": ctx.user_id, "max_attempts": 2})
    await managers.work.enqueue(ctx, other)
    first = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert first is not None and first[1].id == other.id
    assert (await managers.work.fail(first[0], first[1], "boom")).status is WorkStatus.QUEUED
    second = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert second is not None and second[1].id == other.id and second[1].attempts == 2
    failed = await managers.work.fail(second[0], second[1], "boom again")
    assert failed.status is WorkStatus.FAILED
    assert await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE) is None


async def test_extend_lease_and_lease_loss(managers: Managers, ctx: OpContext) -> None:
    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    claimed = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    extended = await managers.work.extend_lease(claimed[0], claimed[1], timedelta(minutes=5))
    assert extended.lease_expires_at is not None
    assert extended.lease_expires_at > utcnow() + timedelta(minutes=4)
    # The token is the fence, not the worker's name: a copy under another
    # token is refused, and so is one that carries no token at all.
    stolen = claimed[1].model_copy(update={"claim_token": new_id()})
    with pytest.raises(LeaseLost):
        await managers.work.extend_lease(claimed[0], stolen, LEASE)
    with pytest.raises(LeaseLost):
        await managers.work.extend_lease(
            claimed[0], claimed[1].model_copy(update={"claim_token": None}), LEASE
        )


async def test_the_same_worker_re_claiming_after_a_requeue_refuses_its_stale_copy(
    managers: Managers, ctx: OpContext
) -> None:
    # A worker whose lease expired, whose item the sweep requeued, and which
    # claims the same item again: the stale task's completion carries the old
    # token and is refused; the new claim is settled by its own token.
    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    first = await managers.work.claim(
        request(), "default", [WorkKind.NOOP], "w1", timedelta(seconds=-1)
    )
    assert first is not None
    stale_ctx, stale = first
    assert await managers.work.requeue_stale(ctx) == 1
    second = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert second is not None
    fresh_ctx, fresh = second
    assert fresh.claimed_by == stale.claimed_by == "w1"
    assert fresh.claim_token != stale.claim_token
    for stale_write in (
        managers.work.complete(stale_ctx, stale),
        managers.work.fail(stale_ctx, stale, "boom"),
        managers.work.extend_lease(stale_ctx, stale, LEASE),
        managers.work.release(stale_ctx, stale),
    ):
        with pytest.raises(LeaseLost):
            await stale_write
    assert (await managers.work.extend_lease(fresh_ctx, fresh, LEASE)).status is WorkStatus.CLAIMED
    done = await managers.work.complete(fresh_ctx, fresh)
    assert done.status is WorkStatus.DONE and done.claim_token is None


async def test_transitions_refuse_a_lost_lease_and_a_missing_item(
    managers: Managers, storage: StorageMemoryImpl, ctx: OpContext
) -> None:
    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    claimed = await managers.work.claim(
        request(), "default", [WorkKind.NOOP], "w1", timedelta(seconds=-1)
    )
    assert claimed is not None
    work_ctx, held = claimed
    assert await managers.work.requeue_stale(ctx) == 1

    with pytest.raises(LeaseLost):
        await managers.work.complete(work_ctx, held)
    with pytest.raises(LeaseLost):
        await managers.work.fail(work_ctx, held, "boom")
    with pytest.raises(LeaseLost):
        await managers.work.defer(work_ctx, held, timedelta(minutes=1))
    with pytest.raises(LeaseLost):
        await managers.work.release(work_ctx, held)
    stored = await storage.get_work_storage().read_item(ctx.org_id, held.id)
    assert stored is not None
    assert stored.status is WorkStatus.QUEUED and stored.last_error == "lease expired"

    taken = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w2", LEASE)
    assert taken is not None and taken[1].claimed_by == "w2"
    with pytest.raises(LeaseLost):
        await managers.work.complete(work_ctx, held)
    with pytest.raises(NotFound):
        await managers.work.complete(work_ctx, held.model_copy(update={"id": new_id()}))
    done = await managers.work.complete(taken[0], taken[1])
    assert done.status is WorkStatus.DONE


async def test_requeue_stale_runs_per_tenant_under_a_maintenance_context(
    managers: Managers, ctx: OpContext
) -> None:
    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    exhausted = make_item().model_copy(update={"created_by": ctx.user_id, "max_attempts": 1})
    await managers.work.enqueue(ctx, exhausted)
    expired = timedelta(seconds=-1)
    assert (
        await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", expired) is not None
    )
    assert (
        await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", expired) is not None
    )

    contexts = await managers.work.maintenance_contexts(request())
    assert [c.org_id for c in contexts] == [ctx.org_id]
    assert all(c.security.role is Role.SERVICE for c in contexts)
    assert await managers.work.requeue_stale(contexts[0]) == 2
    assert await managers.work.requeue_stale(contexts[0]) == 0

    again = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w2", LEASE)
    assert again is not None and again[1].attempts == 2 and again[1].id != exhausted.id
    assert await managers.work.claim(request(), "default", [WorkKind.NOOP], "w2", LEASE) is None


async def test_enqueue_stamps_the_actor_and_clears_the_claim_whatever_the_caller_sent(
    managers: Managers, ctx: OpContext
) -> None:
    sent = make_item().model_copy(
        update={
            "created_by": new_id(),
            "updated_by": new_id(),
            "status": WorkStatus.CLAIMED,
            "claimed_by": "somebody",
            "lease_expires_at": utcnow() + timedelta(hours=1),
            "attempts": 7,
            "last_error": "not mine to say",
        }
    )
    before = utcnow()
    queued = await managers.work.enqueue(ctx, sent)
    assert queued.created_by == ctx.user_id and queued.updated_by == ctx.user_id
    assert queued.created_at >= before and queued.updated_at == queued.created_at
    assert queued.status is WorkStatus.QUEUED and queued.attempts == 0
    assert queued.claimed_by is None and queued.lease_expires_at is None
    assert queued.last_error is None
    assert queued.id == sent.id and queued.idempotency_key == sent.idempotency_key
    # The claim runs under the enqueuer, not under whoever the payload named.
    claimed = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None and claimed[0].user_id == ctx.user_id


async def test_a_retried_enqueue_returns_the_row_as_stored_and_keeps_the_claim(
    managers: Managers, infra: InfraLocalImpl, ctx: OpContext
) -> None:
    seen: list[TopicPayload] = []

    async def record(payload: TopicPayload) -> None:
        seen.append(payload)

    infra.get_topics().subscribe(Topics.WORK_AVAILABLE, "test", record)
    item = make_item().model_copy(update={"created_by": ctx.user_id})
    await managers.work.enqueue(ctx, item)
    claimed = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    work_ctx, held = claimed
    # The producer retries: the row is the claimed one, the claim intact, and
    # the queue is not woken a second time.
    again = await managers.work.enqueue(ctx, item)
    assert again == held and again.status is WorkStatus.CLAIMED and again.claimed_by == "w1"
    assert len([p for p in seen if isinstance(p, WorkAvailablePayload)]) == 1
    done = await managers.work.complete(work_ctx, held)
    assert done.status is WorkStatus.DONE


async def test_enqueue_refuses_a_reused_idempotency_key(managers: Managers, ctx: OpContext) -> None:
    item = make_item().model_copy(update={"created_by": ctx.user_id})
    await managers.work.enqueue(ctx, item)
    duplicate = make_item().model_copy(
        update={"created_by": ctx.user_id, "idempotency_key": item.idempotency_key}
    )
    with pytest.raises(DuplicateWorkItem):
        await managers.work.enqueue(ctx, duplicate)


async def test_enqueue_refuses_a_payload_outside_the_kinds_shape(
    managers: Managers, ctx: OpContext
) -> None:
    # WORK_PAYLOADS fixes the shape per kind; NOOP carries nothing.
    item = make_item().model_copy(update={"created_by": ctx.user_id, "payload": {"extra": 1}})
    with pytest.raises(ValidationFailed):
        await managers.work.enqueue(ctx, item)


async def test_a_failed_item_is_a_dead_letter_with_an_audit_event(
    managers: Managers, infra: InfraLocalImpl, ctx: OpContext
) -> None:
    seen: list[TopicPayload] = []

    async def record(payload: TopicPayload) -> None:
        seen.append(payload)

    infra.get_topics().subscribe(Topics.ENTITY_CHANGED, "test", record)
    item = make_item().model_copy(update={"created_by": ctx.user_id, "max_attempts": 1})
    await managers.work.enqueue(ctx, item)
    claimed = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    work_ctx, claimed_item = claimed
    failed = await managers.work.fail(work_ctx, claimed_item, "boom")
    assert failed.status is WorkStatus.FAILED and failed.updated_by == work_ctx.user_id
    events = await managers.events.get_events(ctx, after_seq=0, limit=10)
    assert [(e.kind, e.target_id, e.payload["last_error"]) for e in events] == [
        (DEAD_LETTER_KIND, item.id, "boom")
    ]
    assert [(p.kind, p.seq) for p in seen if isinstance(p, EntityChangedPayload)] == [
        (DEAD_LETTER_KIND, 1)
    ]


async def test_a_retry_that_still_has_attempts_is_not_a_dead_letter(
    managers: Managers, ctx: OpContext
) -> None:
    item = make_item().model_copy(update={"created_by": ctx.user_id, "max_attempts": 3})
    await managers.work.enqueue(ctx, item)
    claimed = await managers.work.claim(request(), "default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    work_ctx, claimed_item = claimed
    requeued = await managers.work.fail(work_ctx, claimed_item, "again")
    assert requeued.status is WorkStatus.QUEUED
    assert await managers.events.get_events(ctx, after_seq=0, limit=10) == []
