from datetime import timedelta
from uuid import UUID

import pytest
from contracts.idempotency_storage import make_record

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import (
    IdempotencyAttemptLost,
    IdempotencyInProgress,
    IdempotencyKeyReused,
    NotAuthorized,
    NotFound,
)
from tadas.om.idempotency.impl.manager import IdempotencyManagerImpl, IdempotencyOptions
from tadas.om.idempotency.storage.impl.memory import IdempotencyStorageMemoryImpl
from tadas.om.opcontext import (
    AppContext,
    AppType,
    CredentialKind,
    OpContext,
    RequestContext,
    Role,
    build_context,
)
from tadas.om.tenancy.types.role import permissions_of

APP = AppContext(type=AppType.API, version="api@test")


def context(role: Role = Role.MEMBER, org_id: UUID | None = None) -> OpContext:
    return build_context(
        RequestContext(request_id=new_id(), app=APP),
        user_id=new_id(),
        org_id=org_id or new_id(),
        role=role,
        permissions=permissions_of(role),
        credential_kind=CredentialKind.SESSION_TOKEN,
    )


@pytest.fixture
def storage() -> IdempotencyStorageMemoryImpl:
    return IdempotencyStorageMemoryImpl()


@pytest.fixture
def manager(storage: IdempotencyStorageMemoryImpl) -> IdempotencyManagerImpl:
    return IdempotencyManagerImpl(storage, IdempotencyOptions())


async def test_begin_once_then_replay_the_stored_outcome(manager: IdempotencyManagerImpl) -> None:
    ctx = context()
    target = new_id()
    begun = await manager.begin(ctx, "k1", "digest-a", target)
    assert begun.pending and begun.target_id == target
    with pytest.raises(IdempotencyInProgress):
        await manager.begin(ctx, "k1", "digest-a", new_id())
    finished = await manager.finish(ctx, "k1", begun.attempt_id, 201, '{"id":"t1"}')
    assert finished.status == 201 and finished.body == '{"id":"t1"}'
    replayed = await manager.begin(ctx, "k1", "digest-a", new_id())
    assert replayed == finished
    assert (await manager.begin(ctx, "k2", "digest-a", new_id())).pending


async def test_every_begin_mints_its_own_attempt(manager: IdempotencyManagerImpl) -> None:
    ctx = context()
    first = await manager.begin(ctx, "k1", "d", new_id())
    second = await manager.begin(ctx, "k2", "d", new_id())
    assert first.attempt_id != second.attempt_id


async def test_a_reused_key_with_another_request_is_refused(
    manager: IdempotencyManagerImpl,
) -> None:
    ctx = context()
    await manager.begin(ctx, "k1", "digest-a", new_id())
    with pytest.raises(IdempotencyKeyReused):
        await manager.begin(ctx, "k1", "digest-b", new_id())


async def test_keys_are_personal_within_the_tenant(manager: IdempotencyManagerImpl) -> None:
    org_id = new_id()
    ann, bob = context(org_id=org_id), context(org_id=org_id)
    elsewhere = context()
    anns = await manager.begin(ann, "k1", "digest-a", new_id())
    assert anns.pending
    assert (await manager.begin(bob, "k1", "digest-a", new_id())).pending
    assert (await manager.begin(elsewhere, "k1", "digest-a", new_id())).pending
    await manager.finish(ann, "k1", anns.attempt_id, 200, "ann")
    with pytest.raises(IdempotencyInProgress):
        await manager.begin(bob, "k1", "digest-a", new_id())


async def test_release_lets_the_next_attempt_begin_afresh(manager: IdempotencyManagerImpl) -> None:
    ctx = context()
    first = new_id()
    begun = await manager.begin(ctx, "k1", "d", first)
    assert begun.pending
    await manager.release(ctx, "k1", begun.attempt_id)
    second = new_id()
    fresh = await manager.begin(ctx, "k1", "d", second)
    assert fresh.pending and fresh.target_id == second, "afresh: the new attempt's id"
    assert fresh.attempt_id != begun.attempt_id


async def test_finish_needs_a_begun_key_and_write_permission(
    manager: IdempotencyManagerImpl,
) -> None:
    with pytest.raises(NotFound):
        await manager.finish(context(), "never", new_id(), 200, "")
    viewer = context(Role.VIEWER)
    with pytest.raises(NotAuthorized):
        await manager.begin(viewer, "k1", "digest-a", new_id())


async def test_a_finished_record_is_not_finished_or_released_again(
    manager: IdempotencyManagerImpl,
) -> None:
    ctx = context()
    begun = await manager.begin(ctx, "k", "d", new_id())
    await manager.finish(ctx, "k", begun.attempt_id, 201, "first")
    with pytest.raises(IdempotencyAttemptLost):
        await manager.finish(ctx, "k", begun.attempt_id, 201, "second")
    with pytest.raises(IdempotencyAttemptLost):
        await manager.release(ctx, "k", begun.attempt_id)
    assert (await manager.begin(ctx, "k", "d", new_id())).body == "first"


async def test_an_abandoned_pending_record_is_taken_over_with_its_target_id() -> None:
    # The marker landed and the outcome never did (a crash in between, before
    # or after the create committed); once the pending lease has passed a retry
    # runs the request again on the id the first attempt minted, so a create
    # that already landed is found and not repeated.
    manager = IdempotencyManagerImpl(
        IdempotencyStorageMemoryImpl(), IdempotencyOptions(pending_ttl=timedelta(0))
    )
    ctx = context()
    first = new_id()
    begun = await manager.begin(ctx, "k", "d", first)
    assert begun.target_id == first
    taken = await manager.begin(ctx, "k", "d", new_id())
    assert taken.pending and taken.target_id == first, "abandoned: run it again, same id"
    assert taken.attempt_id != begun.attempt_id, "the take-over stamps its own attempt"
    await manager.finish(ctx, "k", taken.attempt_id, 201, "{}")
    replayed = await manager.begin(ctx, "k", "d", new_id())
    assert replayed.status == 201, "finished: replay it"


async def test_a_slow_attempt_that_lost_the_marker_is_refused(
    storage: IdempotencyStorageMemoryImpl, manager: IdempotencyManagerImpl
) -> None:
    # The first attempt is still running when its pending lease passes; the
    # retry takes the marker over and runs the request again on the same id.
    # Whatever the first attempt then does is refused: it can neither record
    # its outcome over the retry's marker nor release the marker the retry
    # holds, and the retry's outcome is the one every later retry replays.
    ctx = context()
    target = new_id()
    slow = await manager.begin(ctx, "k", "d", target)
    stale = slow.model_copy(update={"created_at": utcnow() - timedelta(minutes=5)})
    await storage.write_record(ctx.org_id, stale)  # the lease passed while it ran

    retry = await manager.begin(ctx, "k", "d", new_id())
    assert retry.pending and retry.target_id == target
    assert retry.attempt_id != slow.attempt_id

    with pytest.raises(IdempotencyAttemptLost):
        await manager.finish(ctx, "k", slow.attempt_id, 201, "slow")
    with pytest.raises(IdempotencyAttemptLost):
        await manager.release(ctx, "k", slow.attempt_id)
    stored = await storage.read_record(ctx.org_id, ctx.user_id, "k")
    assert stored == retry, "the slow attempt changed nothing"

    finished = await manager.finish(ctx, "k", retry.attempt_id, 201, "retry")
    assert finished.body == "retry"
    assert (await manager.begin(ctx, "k", "d", new_id())).body == "retry"


async def test_a_record_written_by_hand_carries_its_attempt() -> None:
    assert make_record().attempt_id != make_record().attempt_id
