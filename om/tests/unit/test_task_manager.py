from pathlib import Path
from uuid import UUID

import pytest
from contracts.factories import make_org, make_user

from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.topics import EntityChangedPayload, TopicPayload, Topics
from tadas.infra.topics.memory import TopicsMemoryImpl
from tadas.om.base import new_id, utcnow
from tadas.om.events.impl.manager import EventsManagerImpl, EventsOptions
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.exceptions import NotAuthorized, NotFound, ValidationFailed
from tadas.om.opcontext import AppContext, AppType, CredentialKind, OpContext, Role, build_context
from tadas.om.outbox.impl.relay import OutboxRelayImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.tasks.impl.manager import TasksManagerImpl, TasksOptions
from tadas.om.tasks.storage.impl.memory import TasksStorageMemoryImpl
from tadas.om.tasks.types.filter import TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.role import permissions_of
from tadas.om.tenancy.types.user import User

APP = AppContext(type=AppType.PORTAL, version="portal@test")


class Members(TenancyManagerInterface):
    """Just enough tenancy for the assignee check: the users of one org. A
    partial double: only `get_user` is reached, and any other method fails
    loudly as unimplemented, so the abstract set is cleared below."""

    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}

    async def get_user(self, ctx: OpContext, user_id: UUID) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise NotFound(f"user {user_id} not found")
        return user


Members.__abstractmethods__ = frozenset()


def context(role: Role, org: Org | None = None, members: Members | None = None) -> OpContext:
    user = make_user(new_id())
    if members is not None:
        members.users[user.id] = user
    return build_context(
        user_id=user.id,
        org_id=(org or make_org()).id,
        role=role,
        permissions=permissions_of(role),
        credential_kind=CredentialKind.SESSION_TOKEN,
        app=APP,
        request_id=new_id(),
    )


def make_task(ctx: OpContext, title: str = "Ship it", assignee_id: UUID | None = None) -> Task:
    now = utcnow()
    return Task(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        title=title,
        assignee_id=assignee_id,
    )


@pytest.fixture
def infra(tmp_path: Path) -> InfraLocalImpl:
    return InfraLocalImpl(tmp_path)


@pytest.fixture
def events_storage() -> EventStorageMemoryImpl:
    return EventStorageMemoryImpl()


@pytest.fixture
def events(events_storage: EventStorageMemoryImpl) -> EventsManagerImpl:
    return EventsManagerImpl(events_storage, EventsOptions())


@pytest.fixture
def members() -> Members:
    return Members()  # pyright: ignore[reportAbstractUsage] (a partial double)


@pytest.fixture
def outbox() -> OutboxStorageMemoryImpl:
    return OutboxStorageMemoryImpl()


@pytest.fixture
def manager(
    infra: InfraLocalImpl,
    events_storage: EventStorageMemoryImpl,
    members: Members,
    outbox: OutboxStorageMemoryImpl,
) -> TasksManagerImpl:
    relay = OutboxRelayImpl(outbox, events_storage, infra.get_topics())
    return TasksManagerImpl(TasksStorageMemoryImpl(outbox), members, relay, TasksOptions())


def own(ctx: OpContext, scope: TaskScope) -> TaskFilter:
    return TaskFilter(scope=scope, user_id=ctx.user_id)


async def open_titles(manager: TasksManagerImpl, ctx: OpContext, scope: TaskScope) -> list[str]:
    return [t.title for t in await manager.get_open_tasks(ctx, own(ctx, scope), limit=50)]


async def test_create_update_delete_record_and_push(
    manager: TasksManagerImpl,
    events: EventsManagerImpl,
    infra: InfraLocalImpl,
    outbox: OutboxStorageMemoryImpl,
) -> None:
    seen: list[TopicPayload] = []

    async def record(payload: TopicPayload) -> None:
        seen.append(payload)

    infra.get_topics().subscribe(Topics.ENTITY_CHANGED, "test", record)
    ctx = context(Role.MEMBER)
    created = await manager.create_task(ctx, make_task(ctx))
    assert created.created_by == ctx.user_id and created.status == TaskStatus.OPEN
    assert created.updated_by == ctx.user_id
    assert await manager.get_task(ctx, created.id) == created

    updated = await manager.update_task(ctx, created.model_copy(update={"notes": "carefully"}))
    assert updated.notes == "carefully" and updated.updated_at > created.updated_at
    assert updated.updated_by == ctx.user_id

    deleted = await manager.delete_task(ctx, created.id)
    assert deleted.deleted_at is not None and deleted.deleted_by == ctx.user_id
    assert await manager.get_open_tasks(ctx, own(ctx, TaskScope.TEAM), limit=10) == []
    with pytest.raises(NotFound):
        await manager.get_task(ctx, created.id)
    pushes = [p for p in seen if isinstance(p, EntityChangedPayload)]
    assert [(p.kind, p.target_id, p.seq) for p in pushes] == [
        ("tasks.task.created", created.id, 1),
        ("tasks.task.updated", created.id, 2),
        ("tasks.task.deleted", created.id, 3),
    ]
    # Every push is a record: the event carries the row's id, the snapshot, and
    # the caller's provenance; the outbox row behind it is done.
    recorded = await events.get_events(ctx, after_seq=0, limit=10)
    assert [e.id for e in recorded] == [p.idempotency_key for p in pushes]
    assert recorded[0].payload["title"] == created.title
    assert recorded[0].actor_id == ctx.user_id and recorded[0].request_id == ctx.request_id
    assert recorded[0].app == "portal"
    assert await outbox.read_pending(10) == []


async def test_new_tasks_go_to_the_top_of_the_open_list(manager: TasksManagerImpl) -> None:
    ctx = context(Role.MEMBER)
    for title in ("first", "second", "third"):
        await manager.create_task(ctx, make_task(ctx, title))
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["third", "second", "first"]


async def test_done_leaves_the_open_list_and_reopening_returns_to_the_top(
    manager: TasksManagerImpl,
) -> None:
    ctx = context(Role.MEMBER)
    a = await manager.create_task(ctx, make_task(ctx, "a"))
    await manager.create_task(ctx, make_task(ctx, "b"))
    done = await manager.update_task(ctx, a.model_copy(update={"status": TaskStatus.DONE}))
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b"]
    assert await manager.get_done_tasks(ctx, own(ctx, TaskScope.TEAM), None, limit=10) == [done]

    await manager.create_task(ctx, make_task(ctx, "c"))
    await manager.update_task(ctx, done.model_copy(update={"status": TaskStatus.OPEN}))
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["a", "c", "b"]


async def test_scopes_mine_and_team(manager: TasksManagerImpl, members: Members) -> None:
    org = make_org()
    ann = context(Role.MEMBER, org, members)
    bob = context(Role.MEMBER, org, members)
    await manager.create_task(ann, make_task(ann, "ann's own"))
    await manager.create_task(bob, make_task(bob, "bob's own"))
    await manager.create_task(bob, make_task(bob, "bob gave ann", assignee_id=ann.user_id))
    assert await open_titles(manager, ann, TaskScope.MINE) == ["bob gave ann", "ann's own"]
    assert await open_titles(manager, bob, TaskScope.MINE) == ["bob's own"]
    assert len(await manager.get_open_tasks(ann, own(ann, TaskScope.TEAM), limit=10)) == 3
    with pytest.raises(ValidationFailed):  # `mine` is about the caller and nobody else
        await manager.get_open_tasks(ann, own(bob, TaskScope.MINE), limit=10)


async def test_the_assignee_must_be_a_member(manager: TasksManagerImpl, members: Members) -> None:
    org = make_org()
    ann = context(Role.MEMBER, org, members)
    with pytest.raises(ValidationFailed):
        await manager.create_task(ann, make_task(ann, assignee_id=new_id()))
    task = await manager.create_task(ann, make_task(ann, assignee_id=ann.user_id))
    with pytest.raises(ValidationFailed):
        await manager.update_task(ann, task.model_copy(update={"assignee_id": new_id()}))
    unassigned = await manager.update_task(ann, task.model_copy(update={"assignee_id": None}))
    assert unassigned.assignee_id is None


async def test_move_places_after_an_anchor_or_at_the_top(manager: TasksManagerImpl) -> None:
    ctx = context(Role.MEMBER)
    c = await manager.create_task(ctx, make_task(ctx, "c"))
    b = await manager.create_task(ctx, make_task(ctx, "b"))
    a = await manager.create_task(ctx, make_task(ctx, "a"))
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["a", "b", "c"]

    await manager.move_task(ctx, a.id, after_id=b.id)  # between b and c
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b", "a", "c"]
    await manager.move_task(ctx, b.id, after_id=c.id)  # after the last
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["a", "c", "b"]
    await manager.move_task(ctx, b.id, after_id=None)  # to the top
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b", "a", "c"]
    for _ in range(30):  # halving stays ordered through many moves into one gap
        await manager.move_task(ctx, c.id, after_id=b.id)
        await manager.move_task(ctx, a.id, after_id=b.id)
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b", "a", "c"]

    with pytest.raises(ValidationFailed):
        await manager.move_task(ctx, a.id, after_id=a.id)
    done = await manager.update_task(ctx, c.model_copy(update={"status": TaskStatus.DONE}))
    with pytest.raises(ValidationFailed):
        await manager.move_task(ctx, done.id, after_id=None)
    with pytest.raises(ValidationFailed):
        await manager.move_task(ctx, a.id, after_id=done.id)


async def test_authorize_then_verify(manager: TasksManagerImpl) -> None:
    viewer = context(Role.VIEWER)
    with pytest.raises(NotAuthorized):
        await manager.create_task(viewer, make_task(viewer))
    assert await manager.get_open_tasks(viewer, own(viewer, TaskScope.TEAM), limit=10) == []

    member = context(Role.MEMBER)
    with pytest.raises(ValidationFailed):
        await manager.create_task(member, make_task(member, title="   "))
    task = await manager.create_task(member, make_task(member))
    # A retry presents the same minted id: the row as stored, never a second one.
    assert await manager.create_task(member, task) == task
    with pytest.raises(NotFound):
        await manager.update_task(member, make_task(member))
    with pytest.raises(NotFound):
        await manager.move_task(member, new_id(), after_id=None)
    with pytest.raises(NotFound):
        await manager.delete_task(member, new_id())


async def test_tenancy_holds_across_contexts(manager: TasksManagerImpl) -> None:
    ann, bob = context(Role.MEMBER), context(Role.MEMBER)
    task = await manager.create_task(ann, make_task(ann))
    with pytest.raises(NotFound):
        await manager.get_task(bob, task.id)
    with pytest.raises(NotFound):
        await manager.move_task(bob, task.id, after_id=None)
    assert await manager.get_open_tasks(bob, own(bob, TaskScope.TEAM), limit=10) == []


async def test_lists_are_clamped(infra: InfraLocalImpl, members: Members) -> None:
    outbox = OutboxStorageMemoryImpl()
    events_storage = EventStorageMemoryImpl()
    manager = TasksManagerImpl(
        TasksStorageMemoryImpl(outbox),
        members,
        OutboxRelayImpl(outbox, events_storage, infra.get_topics()),
        TasksOptions(max_limit=2),
    )
    ctx = context(Role.MEMBER)
    for i in range(3):
        await manager.create_task(ctx, make_task(ctx, title=f"t{i}"))
    assert len(await manager.get_open_tasks(ctx, own(ctx, TaskScope.TEAM), limit=1000)) == 2


async def test_a_failed_relay_leaves_the_row_for_the_sweep(
    infra: InfraLocalImpl,
    members: Members,
    events: EventsManagerImpl,
    events_storage: EventStorageMemoryImpl,
) -> None:
    # The request succeeds on the core write; the push is the row's job, and a
    # bus that is down at that moment is caught by the sweep's relay_pending.
    class DownTopics(TopicsMemoryImpl):
        async def publish(self, topic: Topics, payload: TopicPayload) -> None:
            raise RuntimeError("bus down")

    outbox = OutboxStorageMemoryImpl()
    relay = OutboxRelayImpl(outbox, events_storage, DownTopics())
    manager = TasksManagerImpl(TasksStorageMemoryImpl(outbox), members, relay, TasksOptions())
    ctx = context(Role.MEMBER)
    created = await manager.create_task(ctx, make_task(ctx))
    assert await manager.get_task(ctx, created.id) == created
    pending = await outbox.read_pending(10)
    assert [(org, row.kind) for org, row in pending] == [(ctx.org_id, "tasks.task.created")]
    # The event was appended before the publish failed; relaying again is
    # idempotent on the row's id and marks the row done once the bus is back.
    working = OutboxRelayImpl(outbox, events_storage, infra.get_topics())
    assert await working.relay_pending(10) == 1
    assert await outbox.read_pending(10) == []
    assert [e.seq for e in await events.get_events(ctx, after_seq=0, limit=10)] == [1]
