import pytest
from contracts.factories import make_org, make_user

from tadas.om.base import new_id
from tadas.om.events.impl.manager import EventsManagerImpl, EventsOptions
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.opcontext import AppContext, AppType, CredentialKind, OpContext, Role, build_context

APP = AppContext(type=AppType.PORTAL, version="portal@test")


def context(role: Role = Role.MEMBER) -> OpContext:
    return build_context(
        user=make_user(new_id()),
        org=make_org(),
        role=role,
        credential_kind=CredentialKind.SESSION_TOKEN,
        app=APP,
        request_id=new_id(),
    )


@pytest.fixture
def manager() -> EventsManagerImpl:
    return EventsManagerImpl(EventStorageMemoryImpl(), EventsOptions(max_limit=2))


async def test_record_sequences_per_tenant_and_names_the_actor(manager: EventsManagerImpl) -> None:
    ann, bob = context(), context()
    task_id, key = new_id(), new_id()
    first = await manager.record(ann, "task", task_id, "created", key)
    second = await manager.record(ann, "task", task_id, "updated", new_id())
    elsewhere = await manager.record(bob, "task", new_id(), "created", new_id())
    assert (first.seq, second.seq, elsewhere.seq) == (1, 2, 1)
    assert first.actor_id == ann.user_id and first.idempotency_key == key
    assert first.request_id == ann.request_id and elsewhere.request_id == bob.request_id
    assert first.entity == "task" and first.entity_id == task_id and first.action == "created"
    assert await manager.get_events(ann, after_seq=1, limit=10) == [second]
    assert await manager.get_events(bob, after_seq=0, limit=10) == [elsewhere]


async def test_get_events_clamps_the_limit_and_tolerates_a_negative_cursor(
    manager: EventsManagerImpl,
) -> None:
    ctx = context()
    for _ in range(3):
        await manager.record(ctx, "task", new_id(), "created", new_id())
    assert [e.seq for e in await manager.get_events(ctx, after_seq=-5, limit=1000)] == [1, 2]


async def test_a_viewer_records_the_write_it_was_allowed(manager: EventsManagerImpl) -> None:
    # The recording manager authorized the write itself (a viewer may rename
    # themself); the stream row is that write's consequence, so READ is enough.
    viewer = context(Role.VIEWER)
    assert await manager.get_events(viewer, after_seq=0, limit=10) == []
    event = await manager.record(viewer, "user", new_id(), "updated", new_id())
    assert event.seq == 1
    assert event.actor_id == viewer.user_id
