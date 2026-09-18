import pytest
from contracts.event_storage import make_event

from tadas.om.base import new_id
from tadas.om.events.impl.manager import EventsManagerImpl, EventsOptions
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.exceptions import NotAuthorized
from tadas.om.opcontext import AppContext, AppType, CredentialKind, OpContext, Role, build_context
from tadas.om.tenancy.types.role import permissions_of

APP = AppContext(type=AppType.PORTAL, version="portal@test")


def context(role: Role = Role.MEMBER) -> OpContext:
    return build_context(
        user_id=new_id(),
        org_id=new_id(),
        role=role,
        permissions=permissions_of(role),
        credential_kind=CredentialKind.SESSION_TOKEN,
        app=APP,
        request_id=new_id(),
    )


@pytest.fixture
def manager() -> EventsManagerImpl:
    return EventsManagerImpl(EventStorageMemoryImpl(), EventsOptions(max_limit=2))


async def test_append_sequences_per_tenant_and_reads_back_by_seq(
    manager: EventsManagerImpl,
) -> None:
    ann, bob = context(), context()
    first = await manager.append(ann, make_event())
    second = await manager.append(ann, make_event("tasks.task.updated"))
    elsewhere = await manager.append(bob, make_event())
    assert (first.seq, second.seq, elsewhere.seq) == (1, 2, 1)
    assert first.kind == "tasks.task.created" and first.payload == {"title": "t"}
    assert await manager.get_events(ann, after_seq=1, limit=10) == [second]
    assert await manager.get_events(bob, after_seq=0, limit=10) == [elsewhere]


async def test_get_events_clamps_the_limit_and_tolerates_a_negative_cursor(
    manager: EventsManagerImpl,
) -> None:
    ctx = context()
    for _ in range(3):
        await manager.append(ctx, make_event())
    assert [e.seq for e in await manager.get_events(ctx, after_seq=-5, limit=1000)] == [1, 2]


async def test_the_stream_is_read_with_read_and_is_append_only(manager: EventsManagerImpl) -> None:
    # An append-only entity: no update, no delete, and the read needs READ.
    viewer = context(Role.VIEWER)
    await manager.append(viewer, make_event())
    assert [e.seq for e in await manager.get_events(viewer, after_seq=0, limit=10)] == [1]
    assert not hasattr(manager, "update_event") and not hasattr(manager, "delete_event")
    no_read = viewer.model_copy(
        update={"security": viewer.security.model_copy(update={"permissions": ()})}
    )
    with pytest.raises(NotAuthorized):
        await manager.get_events(no_read, after_seq=0, limit=10)
