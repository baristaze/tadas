from datetime import timedelta
from pathlib import Path

import pytest
from contracts.work_storage import make_item

from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.topics import TopicPayload, Topics, WorkAvailablePayload
from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import LeaseLost
from tadas.om.opcontext import AppContext, AppType, CredentialKind, OpContext, Role
from tadas.om.root import Managers, build_managers
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.work.types.work_item import WorkKind, WorkStatus

LEASE = timedelta(seconds=30)


@pytest.fixture
def infra(tmp_path: Path) -> InfraLocalImpl:
    return InfraLocalImpl(tmp_path)


@pytest.fixture
def managers(infra: InfraLocalImpl) -> Managers:
    return build_managers(StorageMemoryImpl(), infra)


@pytest.fixture
async def ctx(managers: Managers) -> OpContext:
    org = await managers.tenancy.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    login = await managers.tenancy.login("ann@example.test", "pw-1234")
    issued = await managers.tenancy.exchange_login(login.token, org.id)
    return await managers.tenancy.authenticate(
        issued.token, AppContext(type=AppType.PORTAL, version="portal@test"), new_id()
    )


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
    assert seen[0].queue == "default" and seen[0].kind == "NOOP"
    assert seen[0].idempotency_key == item.idempotency_key

    claimed = await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    work_ctx, claimed_item = claimed
    assert work_ctx.org_id == ctx.org_id
    assert work_ctx.user_id == ctx.user_id
    assert work_ctx.security.role is Role.SERVICE
    assert work_ctx.security.credential_kind is CredentialKind.INTERNAL
    assert work_ctx.app.type is AppType.WORKER
    assert claimed_item.claimed_by == "w1"

    done = await managers.work.complete(work_ctx, claimed_item)
    assert done.status is WorkStatus.DONE and done.claimed_by is None
    assert await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE) is None


async def test_defer_and_release_hand_back_without_spending_an_attempt(
    managers: Managers, ctx: OpContext
) -> None:
    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    claimed = await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    deferred = await managers.work.defer(claimed[0], claimed[1], timedelta(hours=1))
    assert deferred.status is WorkStatus.QUEUED and deferred.attempts == 0
    assert deferred.available_at > utcnow() + timedelta(minutes=59)
    assert await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE) is None

    released = await managers.work.release(
        claimed[0], deferred.model_copy(update={"available_at": utcnow()})
    )
    assert released.attempts == 0 and released.status is WorkStatus.QUEUED
    again = await managers.work.claim("default", [WorkKind.NOOP], "w2", LEASE)
    assert again is not None and again[1].attempts == 1


async def test_fail_requeues_with_a_growing_delay_then_fails(
    managers: Managers, ctx: OpContext
) -> None:
    item = make_item().model_copy(update={"created_by": ctx.user_id, "max_attempts": 2})
    await managers.work.enqueue(ctx, item)
    first = await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE)
    assert first is not None
    requeued = await managers.work.fail(first[0], first[1], "boom")
    assert requeued.status is WorkStatus.QUEUED and requeued.last_error == "boom"
    assert requeued.available_at > utcnow() + timedelta(seconds=20)

    ready = requeued.model_copy(update={"available_at": utcnow()})
    await managers.work.release(first[0], ready.model_copy(update={"attempts": 2}))
    second = await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE)
    assert second is not None and second[1].attempts == 2
    failed = await managers.work.fail(second[0], second[1], "boom again")
    assert failed.status is WorkStatus.FAILED
    assert await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE) is None


async def test_extend_lease_and_lease_loss(managers: Managers, ctx: OpContext) -> None:
    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    claimed = await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    extended = await managers.work.extend_lease(claimed[0], claimed[1], timedelta(minutes=5))
    assert extended.lease_expires_at is not None
    assert extended.lease_expires_at > utcnow() + timedelta(minutes=4)
    stolen = claimed[1].model_copy(update={"claimed_by": "w2"})
    with pytest.raises(LeaseLost):
        await managers.work.extend_lease(claimed[0], stolen, LEASE)


async def test_requeue_stale_and_maintenance_contexts(managers: Managers, ctx: OpContext) -> None:
    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    exhausted = make_item().model_copy(update={"created_by": ctx.user_id, "max_attempts": 1})
    await managers.work.enqueue(ctx, exhausted)
    expired = timedelta(seconds=-1)
    assert await managers.work.claim("default", [WorkKind.NOOP], "w1", expired) is not None
    assert await managers.work.claim("default", [WorkKind.NOOP], "w1", expired) is not None
    assert await managers.work.requeue_stale() == 2
    assert await managers.work.requeue_stale() == 0
    contexts = await managers.work.maintenance_contexts()
    assert [c.org_id for c in contexts] == [ctx.org_id]
    assert all(c.security.role is Role.SERVICE for c in contexts)
