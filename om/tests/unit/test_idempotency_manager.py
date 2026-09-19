from datetime import timedelta
from uuid import UUID

import pytest

from tadas.om.base import new_id
from tadas.om.exceptions import IdempotencyInProgress, IdempotencyKeyReused, NotAuthorized, NotFound
from tadas.om.idempotency.impl.manager import IdempotencyManagerImpl, IdempotencyOptions
from tadas.om.idempotency.storage.impl.memory import IdempotencyStorageMemoryImpl
from tadas.om.opcontext import AppContext, AppType, CredentialKind, OpContext, Role, build_context
from tadas.om.tenancy.types.role import permissions_of

APP = AppContext(type=AppType.API, version="api@test")


def context(role: Role = Role.MEMBER, org_id: UUID | None = None) -> OpContext:
    return build_context(
        user_id=new_id(),
        org_id=org_id or new_id(),
        role=role,
        permissions=permissions_of(role),
        credential_kind=CredentialKind.SESSION_TOKEN,
        app=APP,
        request_id=new_id(),
    )


@pytest.fixture
def manager() -> IdempotencyManagerImpl:
    return IdempotencyManagerImpl(IdempotencyStorageMemoryImpl(), IdempotencyOptions())


async def test_begin_once_then_replay_the_stored_outcome(manager: IdempotencyManagerImpl) -> None:
    ctx = context()
    target = new_id()
    begun = await manager.begin(ctx, "k1", "digest-a", target)
    assert begun.pending and begun.target_id == target
    with pytest.raises(IdempotencyInProgress):
        await manager.begin(ctx, "k1", "digest-a", new_id())
    finished = await manager.finish(ctx, "k1", 201, '{"id":"t1"}')
    assert finished.status == 201 and finished.body == '{"id":"t1"}'
    replayed = await manager.begin(ctx, "k1", "digest-a", new_id())
    assert replayed == finished
    assert (await manager.begin(ctx, "k2", "digest-a", new_id())).pending


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
    assert (await manager.begin(ann, "k1", "digest-a", new_id())).pending
    assert (await manager.begin(bob, "k1", "digest-a", new_id())).pending
    assert (await manager.begin(elsewhere, "k1", "digest-a", new_id())).pending
    await manager.finish(ann, "k1", 200, "ann")
    with pytest.raises(IdempotencyInProgress):
        await manager.begin(bob, "k1", "digest-a", new_id())


async def test_finish_needs_a_begun_key_and_write_permission(
    manager: IdempotencyManagerImpl,
) -> None:
    with pytest.raises(NotFound):
        await manager.finish(context(), "never", 200, "")
    viewer = context(Role.VIEWER)
    with pytest.raises(NotAuthorized):
        await manager.begin(viewer, "k1", "digest-a", new_id())


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
    assert (await manager.begin(ctx, "k", "d", first)).target_id == first
    taken = await manager.begin(ctx, "k", "d", new_id())
    assert taken.pending and taken.target_id == first, "abandoned: run it again, same id"
    await manager.finish(ctx, "k", 201, "{}")
    replayed = await manager.begin(ctx, "k", "d", new_id())
    assert replayed.status == 201, "finished: replay it"
