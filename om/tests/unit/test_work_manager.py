from datetime import timedelta
from pathlib import Path

import pytest
from contracts.work_storage import make_item

from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.topics import EntityChangedPayload, TopicPayload, Topics, WorkAvailablePayload
from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import LeaseLost, NotFound, ValidationFailed
from tadas.om.opcontext import AppContext, AppType, CredentialKind, OpContext, Role
from tadas.om.root import Managers, build_managers
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.work.impl.manager import DEAD_LETTER_KIND
from tadas.om.work.types.work_item import WorkKind, WorkStatus

LEASE = timedelta(seconds=30)


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
    _, org = await managers.tenancy.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
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
    assert seen[0].lane == "default" and seen[0].kind == "NOOP"
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
    managers: Managers, storage: StorageMemoryImpl, ctx: OpContext
) -> None:
    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    claimed = await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    deferred = await managers.work.defer(claimed[0], claimed[1], timedelta(hours=1))
    assert deferred.status is WorkStatus.QUEUED and deferred.attempts == 0
    assert deferred.available_at > utcnow() + timedelta(minutes=59)
    assert await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE) is None

    ready = deferred.model_copy(update={"available_at": utcnow()})
    await storage.get_work_storage().write_item(ctx.org_id, ready)
    reclaimed = await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE)
    assert reclaimed is not None and reclaimed[1].attempts == 1
    released = await managers.work.release(reclaimed[0], reclaimed[1])
    assert released.attempts == 0 and released.status is WorkStatus.QUEUED
    again = await managers.work.claim("default", [WorkKind.NOOP], "w2", LEASE)
    assert again is not None and again[1].attempts == 1


async def test_fail_requeues_with_a_growing_delay_then_fails(
    managers: Managers, storage: StorageMemoryImpl, ctx: OpContext
) -> None:
    item = make_item().model_copy(update={"created_by": ctx.user_id, "max_attempts": 2})
    await managers.work.enqueue(ctx, item)
    first = await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE)
    assert first is not None
    requeued = await managers.work.fail(first[0], first[1], "boom")
    assert requeued.status is WorkStatus.QUEUED and requeued.last_error == "boom"
    assert requeued.available_at > utcnow() + timedelta(seconds=20)
    assert await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE) is None

    ready = requeued.model_copy(update={"available_at": utcnow()})
    await storage.get_work_storage().write_item(ctx.org_id, ready)
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


async def test_transitions_refuse_a_lost_lease_and_a_missing_item(
    managers: Managers, storage: StorageMemoryImpl, ctx: OpContext
) -> None:
    await managers.work.enqueue(ctx, make_item().model_copy(update={"created_by": ctx.user_id}))
    claimed = await managers.work.claim("default", [WorkKind.NOOP], "w1", timedelta(seconds=-1))
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

    taken = await managers.work.claim("default", [WorkKind.NOOP], "w2", LEASE)
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
    assert await managers.work.claim("default", [WorkKind.NOOP], "w1", expired) is not None
    assert await managers.work.claim("default", [WorkKind.NOOP], "w1", expired) is not None

    contexts = await managers.work.maintenance_contexts()
    assert [c.org_id for c in contexts] == [ctx.org_id]
    assert all(c.security.role is Role.SERVICE for c in contexts)
    assert await managers.work.requeue_stale(contexts[0]) == 2
    assert await managers.work.requeue_stale(contexts[0]) == 0

    again = await managers.work.claim("default", [WorkKind.NOOP], "w2", LEASE)
    assert again is not None and again[1].attempts == 2 and again[1].id != exhausted.id
    assert await managers.work.claim("default", [WorkKind.NOOP], "w2", LEASE) is None


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
    claimed = await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE)
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
    claimed = await managers.work.claim("default", [WorkKind.NOOP], "w1", LEASE)
    assert claimed is not None
    work_ctx, claimed_item = claimed
    requeued = await managers.work.fail(work_ctx, claimed_item, "again")
    assert requeued.status is WorkStatus.QUEUED
    assert await managers.events.get_events(ctx, after_seq=0, limit=10) == []
