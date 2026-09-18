from uuid import UUID

import pytest

from tadas.om.base import new_id
from tadas.om.exceptions import IdempotencyKeyReused, NotAuthorized, NotFound
from tadas.om.idempotency.impl.manager import IdempotencyManagerImpl
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
    return IdempotencyManagerImpl(IdempotencyStorageMemoryImpl())


async def test_begin_once_then_replay_the_stored_outcome(manager: IdempotencyManagerImpl) -> None:
    ctx = context()
    assert await manager.begin(ctx, "k1", "digest-a") is None
    in_flight = await manager.begin(ctx, "k1", "digest-a")
    assert in_flight is not None and in_flight.pending
    finished = await manager.finish(ctx, "k1", 201, '{"id":"t1"}')
    assert finished.status == 201 and finished.body == '{"id":"t1"}'
    replayed = await manager.begin(ctx, "k1", "digest-a")
    assert replayed == finished
    assert await manager.begin(ctx, "k2", "digest-a") is None


async def test_a_reused_key_with_another_request_is_refused(
    manager: IdempotencyManagerImpl,
) -> None:
    ctx = context()
    assert await manager.begin(ctx, "k1", "digest-a") is None
    with pytest.raises(IdempotencyKeyReused):
        await manager.begin(ctx, "k1", "digest-b")


async def test_keys_are_personal_within_the_tenant(manager: IdempotencyManagerImpl) -> None:
    org_id = new_id()
    ann, bob = context(org_id=org_id), context(org_id=org_id)
    elsewhere = context()
    assert await manager.begin(ann, "k1", "digest-a") is None
    assert await manager.begin(bob, "k1", "digest-a") is None
    assert await manager.begin(elsewhere, "k1", "digest-a") is None
    await manager.finish(ann, "k1", 200, "ann")
    replayed = await manager.begin(bob, "k1", "digest-a")
    assert replayed is not None and replayed.pending


async def test_finish_needs_a_begun_key_and_write_permission(
    manager: IdempotencyManagerImpl,
) -> None:
    with pytest.raises(NotFound):
        await manager.finish(context(), "never", 200, "")
    viewer = context(Role.VIEWER)
    with pytest.raises(NotAuthorized):
        await manager.begin(viewer, "k1", "digest-a")
