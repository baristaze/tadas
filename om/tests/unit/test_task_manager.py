from collections.abc import Callable, Coroutine
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from contracts.factories import make_org, make_user
from contracts.outbox_storage import claim_all
from contracts.plans import ON_TEAM

from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.topics import EntityChangedPayload, TopicPayload, Topics
from tadas.infra.topics.memory import TopicsMemoryImpl
from tadas.om.base import PROVENANCE_FIELDS, new_id, utcnow
from tadas.om.events.impl.manager import EventsManagerImpl, EventsOptions
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.exceptions import NotAuthorized, NotFound, PreconditionFailed, ValidationFailed
from tadas.om.opcontext import (
    AppContext,
    AppType,
    CredentialKind,
    OpContext,
    RequestContext,
    Role,
    build_context,
)
from tadas.om.outbox.impl.relay import OutboxOptions, OutboxRelayImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.outbox.types.row import OutboxRow, outbox_row
from tadas.om.tasks.impl.manager import TasksManagerImpl, TasksOptions
from tadas.om.tasks.storage.impl.memory import TasksStorageMemoryImpl
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.role import permissions_of
from tadas.om.tenancy.types.user import User

APP = AppContext(type=AppType.PORTAL, version="portal@test")


class Members(TenancyManagerInterface):
    """Just enough tenancy for the assignee check and for the sweep's question:
    the users of one org, and whether the tenant is past its retention. A
    partial double: only `get_user` and `tenant_expired` are reached, and any
    other method fails loudly as unimplemented, so the abstract set is cleared
    below."""

    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.expired = False

    async def get_user(self, ctx: OpContext, user_id: UUID) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise NotFound(f"user {user_id} not found")
        return user

    async def tenant_expired(self, ctx: OpContext) -> bool:
        return self.expired


Members.__abstractmethods__ = frozenset()


def context(role: Role, org: Org | None = None, members: Members | None = None) -> OpContext:
    user = make_user(new_id())
    if members is not None:
        members.users[user.id] = user
    return build_context(
        RequestContext(request_id=new_id(), app=APP),
        user_id=user.id,
        org_id=(org or make_org()).id,
        role=role,
        permissions=permissions_of(role),
        credential_kind=CredentialKind.SESSION_TOKEN,
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
def events(events_storage: EventStorageMemoryImpl, members: Members) -> EventsManagerImpl:
    return EventsManagerImpl(events_storage, members, EventsOptions())


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
    return TasksManagerImpl(
        TasksStorageMemoryImpl(outbox), members, relay, TasksOptions(), entitlements=ON_TEAM
    )


def _row(ctx: OpContext, task: Task) -> OutboxRow:
    """One outbox row, for the writes a test makes straight to storage."""
    return outbox_row(ctx, "tasks.task.updated", task.id, {})


def own(ctx: OpContext, scope: TaskScope) -> TaskFilter:
    return TaskFilter(scope=scope, user_id=ctx.user_id)


async def open_titles(manager: TasksManagerImpl, ctx: OpContext, scope: TaskScope) -> list[str]:
    page = await manager.get_open_tasks(ctx, own(ctx, scope), None, limit=50)
    return [t.title for t in page.items]


async def open_page(manager: TasksManagerImpl, ctx: OpContext, limit: int = 10) -> tuple[Task, ...]:
    return (await manager.get_open_tasks(ctx, own(ctx, TaskScope.TEAM), None, limit)).items


async def move(
    manager: TasksManagerImpl, ctx: OpContext, task_id: UUID, after_id: UUID | None
) -> Task:
    """A move from a fresh read, the way a client that just listed does it."""
    current = await manager.get_task(ctx, task_id)
    return await manager.move_task(ctx, task_id, after_id, current.version)


async def delete(manager: TasksManagerImpl, ctx: OpContext, task_id: UUID) -> Task:
    return await manager.delete_task(ctx, task_id, (await manager.get_task(ctx, task_id)).version)


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

    updated = await manager.update_task(
        ctx, created.model_copy(update={"notes": "carefully"}), created.version
    )
    assert updated.notes == "carefully" and updated.updated_at > created.updated_at
    assert updated.updated_by == ctx.user_id
    assert (created.version, updated.version) == (1, 2)

    deleted = await manager.delete_task(ctx, created.id, updated.version)
    assert deleted.deleted_at is not None and deleted.deleted_by == ctx.user_id
    assert deleted.version == 3
    assert await open_page(manager, ctx) == ()
    with pytest.raises(NotFound):
        await manager.get_task(ctx, created.id)
    pushes = [p for p in seen if isinstance(p, EntityChangedPayload)]
    assert [(p.kind, p.target_id, p.seq) for p in pushes] == [
        ("tasks.task.created", created.id, 1),
        ("tasks.task.updated", created.id, 2),
        ("tasks.task.deleted", created.id, 3),
    ]
    # Every push is a record: the event carries the row's id and the caller's
    # provenance, and ids only, never a field's value; the outbox row behind
    # it is done.
    recorded = await events.get_events(ctx, after_seq=0, limit=10)
    assert [e.id for e in recorded] == [p.idempotency_key for p in pushes]
    assert [e.payload for e in recorded] == [{}, {}, {}]
    assert recorded[0].actor_id == ctx.user_id and recorded[0].request_id == ctx.request_id
    assert recorded[0].app == "portal"
    assert await claim_all(outbox) == []


async def test_update_keeps_the_provenance_as_stored(manager: TasksManagerImpl) -> None:
    # The copy on update starts from the stored row: a caller may change the
    # title, the notes, the status, the assignee, and nothing about who made
    # the row or whether it is deleted, whatever its entity says.
    ann, bob = context(Role.MEMBER), context(Role.MEMBER)
    created = await manager.create_task(ann, make_task(ann))
    forged = created.model_copy(
        update={
            "title": "renamed",
            "created_at": created.created_at - timedelta(days=1),
            "created_by": bob.user_id,
            "deleted_at": utcnow(),
            "deleted_by": bob.user_id,
        }
    )
    updated = await manager.update_task(ann, forged, created.version)
    assert updated.title == "renamed"
    assert updated.created_at == created.created_at and updated.created_by == ann.user_id
    assert updated.deleted_at is None and updated.deleted_by is None
    assert await manager.get_task(ann, created.id) == updated
    assert PROVENANCE_FIELDS == {"created_at", "created_by", "deleted_at", "deleted_by"}

    # A deleted row is not brought back by an entity with the deletion cleared.
    deleted = await manager.delete_task(ann, created.id, updated.version)
    revived = deleted.model_copy(update={"deleted_at": None, "deleted_by": None})
    with pytest.raises(NotFound):
        await manager.update_task(ann, revived, deleted.version)
    assert await open_page(manager, ann) == ()


async def test_update_keeps_the_manager_owned_fields_and_takes_the_callers_version(
    manager: TasksManagerImpl,
) -> None:
    # The place in the open list and the version are the manager's: an entity
    # that names others changes neither. The version the write compares with
    # is the one the caller names beside the entity, never the entity's own.
    ctx = context(Role.MEMBER)
    first = await manager.create_task(ctx, make_task(ctx, "first"))
    second = await manager.create_task(ctx, make_task(ctx, "second"))
    assert Task.MANAGER_OWNED_FIELDS == ("position", "version")
    forged = first.model_copy(update={"title": "renamed", "position": -1e9, "version": 99})
    updated = await manager.update_task(ctx, forged, first.version)
    assert updated.title == "renamed"
    assert updated.position == first.position and updated.version == first.version + 1
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["second", "renamed"]
    stale = second.model_copy(update={"title": "stale"})
    with pytest.raises(PreconditionFailed):
        await manager.update_task(ctx, stale, second.version + 1)
    assert (await manager.get_task(ctx, second.id)).title == "second"


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
    done = await manager.update_task(
        ctx, a.model_copy(update={"status": TaskStatus.DONE}), a.version
    )
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b"]
    done_page = await manager.get_done_tasks(ctx, own(ctx, TaskScope.TEAM), None, limit=10)
    assert done_page.items == (done,) and not done_page.has_more

    await manager.create_task(ctx, make_task(ctx, "c"))
    await manager.update_task(
        ctx, done.model_copy(update={"status": TaskStatus.OPEN}), done.version
    )
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
    assert len(await open_page(manager, ann)) == 3
    with pytest.raises(ValidationFailed):  # `mine` is about the caller and nobody else
        await manager.get_open_tasks(ann, own(bob, TaskScope.MINE), None, limit=10)


async def test_the_assignee_must_be_a_member(manager: TasksManagerImpl, members: Members) -> None:
    org = make_org()
    ann = context(Role.MEMBER, org, members)
    with pytest.raises(ValidationFailed):
        await manager.create_task(ann, make_task(ann, assignee_id=new_id()))
    task = await manager.create_task(ann, make_task(ann, assignee_id=ann.user_id))
    with pytest.raises(ValidationFailed):
        await manager.update_task(
            ann, task.model_copy(update={"assignee_id": new_id()}), task.version
        )
    unassigned = await manager.update_task(
        ann, task.model_copy(update={"assignee_id": None}), task.version
    )
    assert unassigned.assignee_id is None


async def test_an_update_keeps_an_assignee_who_left_the_org(
    manager: TasksManagerImpl, members: Members
) -> None:
    """The assignee is checked when the assignment changes, not over one
    already stored. Removing a member leaves their tasks assigned to them, and
    every other edit of such a task - done, reopened, retitled - must still
    land; only a new assignment is held to membership."""
    org = make_org()
    ann = context(Role.MEMBER, org, members)
    bob = context(Role.MEMBER, org, members)
    task = await manager.create_task(ann, make_task(ann, "hand over", assignee_id=bob.user_id))
    del members.users[bob.user_id]  # bob is removed from the org
    done = await manager.update_task(
        ann, task.model_copy(update={"status": TaskStatus.DONE}), task.version
    )
    assert done.status is TaskStatus.DONE and done.assignee_id == bob.user_id
    retitled = await manager.update_task(
        ann, done.model_copy(update={"title": "handed over"}), done.version
    )
    assert retitled.title == "handed over" and retitled.assignee_id == bob.user_id
    with pytest.raises(ValidationFailed):  # a new assignment is still checked
        await manager.update_task(
            ann, retitled.model_copy(update={"assignee_id": new_id()}), retitled.version
        )
    cleared = await manager.update_task(
        ann, retitled.model_copy(update={"assignee_id": None}), retitled.version
    )
    assert cleared.assignee_id is None


async def test_move_places_after_an_anchor_or_at_the_top(manager: TasksManagerImpl) -> None:
    ctx = context(Role.MEMBER)
    c = await manager.create_task(ctx, make_task(ctx, "c"))
    b = await manager.create_task(ctx, make_task(ctx, "b"))
    a = await manager.create_task(ctx, make_task(ctx, "a"))
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["a", "b", "c"]

    await move(manager, ctx, a.id, after_id=b.id)  # between b and c
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b", "a", "c"]
    await move(manager, ctx, b.id, after_id=c.id)  # after the last
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["a", "c", "b"]
    await move(manager, ctx, b.id, after_id=None)  # to the top
    assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b", "a", "c"]
    for _ in range(60):  # halving stays ordered through many moves into one gap
        await move(manager, ctx, c.id, after_id=b.id)
        assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b", "c", "a"]
        await move(manager, ctx, a.id, after_id=b.id)
        assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b", "a", "c"]

    with pytest.raises(ValidationFailed):
        await move(manager, ctx, a.id, after_id=a.id)
    current = await manager.get_task(ctx, c.id)
    done = await manager.update_task(
        ctx, current.model_copy(update={"status": TaskStatus.DONE}), current.version
    )
    with pytest.raises(ValidationFailed):
        await move(manager, ctx, done.id, after_id=None)
    with pytest.raises(ValidationFailed):
        await move(manager, ctx, a.id, after_id=done.id)


async def test_authorize_then_verify(manager: TasksManagerImpl) -> None:
    viewer = context(Role.VIEWER)
    with pytest.raises(NotAuthorized):
        await manager.create_task(viewer, make_task(viewer))
    assert await open_page(manager, viewer) == ()

    member = context(Role.MEMBER)
    with pytest.raises(ValidationFailed):
        await manager.create_task(member, make_task(member, title="   "))
    task = await manager.create_task(member, make_task(member))
    # A retry presents the same minted id: the row as stored, never a second one.
    assert await manager.create_task(member, task) == task
    with pytest.raises(NotFound):
        await manager.update_task(member, make_task(member), 1)
    with pytest.raises(NotFound):
        await manager.move_task(member, new_id(), None, 1)
    with pytest.raises(NotFound):
        await manager.delete_task(member, new_id(), 1)


async def test_tenancy_holds_across_contexts(manager: TasksManagerImpl) -> None:
    ann, bob = context(Role.MEMBER), context(Role.MEMBER)
    task = await manager.create_task(ann, make_task(ann))
    with pytest.raises(NotFound):
        await manager.get_task(bob, task.id)
    with pytest.raises(NotFound):
        await manager.move_task(bob, task.id, None, task.version)
    assert await open_page(manager, bob) == ()


async def test_two_updates_from_one_snapshot_one_wins(manager: TasksManagerImpl) -> None:
    # Ann and Bob both read the task at version 1. Ann's edit lands and the
    # task is at version 2; Bob's edit still names version 1, so it is refused
    # as a failed precondition and Ann's title stands. Bob reads again and his edit lands.
    org = make_org()
    ann, bob = context(Role.MEMBER, org), context(Role.MEMBER, org)
    created = await manager.create_task(ann, make_task(ann, "as read"))
    anns = await manager.update_task(
        ann, created.model_copy(update={"title": "ann's"}), created.version
    )
    with pytest.raises(PreconditionFailed) as refused:
        await manager.update_task(
            bob, created.model_copy(update={"title": "bob's"}), created.version
        )
    assert refused.value.http_status == 412 and refused.value.code == "precondition_failed"
    assert await manager.get_task(bob, created.id) == anns
    bobs = await manager.update_task(bob, anns.model_copy(update={"title": "bob's"}), anns.version)
    assert bobs.version == 3 and bobs.updated_by == bob.user_id


async def test_a_delete_racing_an_edit_cannot_be_undone_by_the_edit(
    manager: TasksManagerImpl,
) -> None:
    org = make_org()
    ann, bob = context(Role.MEMBER, org), context(Role.MEMBER, org)
    created = await manager.create_task(ann, make_task(ann))
    # The delete lands first: the edit, from the snapshot before it, finds the
    # task gone. Its snapshot says "not deleted", and that never comes back.
    await manager.delete_task(ann, created.id, created.version)
    with pytest.raises(NotFound):
        await manager.update_task(
            bob, created.model_copy(update={"title": "still here?"}), created.version
        )
    with pytest.raises(NotFound):
        await manager.get_task(bob, created.id)
    # The edit lands first: the delete, from the snapshot before it, is refused
    # and the edited task stays; a delete from a fresh read goes through.
    again = await manager.create_task(ann, make_task(ann, "edited then deleted"))
    edited = await manager.update_task(
        bob, again.model_copy(update={"title": "edited"}), again.version
    )
    with pytest.raises(PreconditionFailed):
        await manager.delete_task(ann, again.id, again.version)
    assert await manager.get_task(ann, again.id) == edited
    assert (await delete(manager, ann, again.id)).deleted_at is not None


async def test_a_write_that_lands_between_the_read_and_the_write_is_refused(
    infra: InfraLocalImpl, members: Members, events_storage: EventStorageMemoryImpl
) -> None:
    # The window the version closes: the manager read the task, and before its
    # write reaches storage another writer's delete lands. The write names the
    # version it read, so storage refuses it instead of overwriting the delete.
    class Interleaved(TasksStorageMemoryImpl):
        before_first_update: Callable[[], Coroutine[Any, Any, None]] | None = None

        async def update_task(
            self,
            org_id: UUID,
            task: Task,
            expected_version: int,
            outbox_rows: tuple[OutboxRow, ...],
        ) -> None:
            hook, self.before_first_update = self.before_first_update, None
            if hook is not None:
                await hook()
            await super().update_task(org_id, task, expected_version, outbox_rows)

    outbox = OutboxStorageMemoryImpl()
    storage = Interleaved(outbox)
    relay = OutboxRelayImpl(outbox, events_storage, infra.get_topics())
    manager = TasksManagerImpl(storage, members, relay, TasksOptions(), entitlements=ON_TEAM)
    org = make_org()
    ann, bob = context(Role.MEMBER, org), context(Role.MEMBER, org)
    created = await manager.create_task(ann, make_task(ann))

    async def bob_deletes() -> None:
        await manager.delete_task(bob, created.id, created.version)

    storage.before_first_update = bob_deletes
    with pytest.raises(PreconditionFailed):
        await manager.update_task(
            ann, created.model_copy(update={"title": "overwrite?"}), created.version
        )
    stored = await storage.read_task(org.id, created.id)
    assert stored is not None and stored.deleted_at is not None and stored.title == "Ship it"


async def test_lists_are_clamped(infra: InfraLocalImpl, members: Members) -> None:
    outbox = OutboxStorageMemoryImpl()
    events_storage = EventStorageMemoryImpl()
    manager = TasksManagerImpl(
        TasksStorageMemoryImpl(outbox),
        members,
        OutboxRelayImpl(outbox, events_storage, infra.get_topics()),
        TasksOptions(max_limit=2),
        entitlements=ON_TEAM,
    )
    ctx = context(Role.MEMBER)
    for i in range(3):
        await manager.create_task(ctx, make_task(ctx, title=f"t{i}"))
    # The clamp is on the page; the lookahead still sees past it, so the
    # page says another follows instead of hiding the third task.
    page = await manager.get_open_tasks(ctx, own(ctx, TaskScope.TEAM), None, limit=1000)
    assert len(page.items) == 2 and page.has_more
    last = OpenTaskCursor(position=page.items[-1].position, id=page.items[-1].id)
    rest = await manager.get_open_tasks(ctx, own(ctx, TaskScope.TEAM), last, limit=1000)
    assert [t.title for t in rest.items] == ["t0"] and not rest.has_more


async def test_a_client_paging_at_the_clamp_sees_every_task(manager: TasksManagerImpl) -> None:
    # 201 open and 201 done tasks against the default clamp of 200: the 201st
    # row of each list is the one the lookahead exists for.
    ctx = context(Role.MEMBER)
    for i in range(201):
        open_task = await manager.create_task(ctx, make_task(ctx, title=f"open {i}"))
        done_task = await manager.create_task(ctx, make_task(ctx, title=f"done {i}"))
        await manager.update_task(
            ctx, done_task.model_copy(update={"status": TaskStatus.DONE}), done_task.version
        )
        assert open_task.status == TaskStatus.OPEN

    seen_open: list[str] = []
    after: OpenTaskCursor | None = None
    while True:
        page = await manager.get_open_tasks(ctx, own(ctx, TaskScope.TEAM), after, limit=200)
        seen_open += [t.title for t in page.items]
        if not page.has_more:
            break
        after = OpenTaskCursor(position=page.items[-1].position, id=page.items[-1].id)
    assert len(seen_open) == 201 and len(set(seen_open)) == 201
    assert seen_open[0] == "open 200" and seen_open[-1] == "open 0"

    seen_done: list[str] = []
    before: TaskCursor | None = None
    while True:
        page = await manager.get_done_tasks(ctx, own(ctx, TaskScope.TEAM), before, limit=200)
        seen_done += [t.title for t in page.items]
        if not page.has_more:
            break
        before = TaskCursor(updated_at=page.items[-1].updated_at, id=page.items[-1].id)
    assert len(seen_done) == 201 and len(set(seen_done)) == 201


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
    manager = TasksManagerImpl(
        TasksStorageMemoryImpl(outbox), members, relay, TasksOptions(), entitlements=ON_TEAM
    )
    ctx = context(Role.MEMBER)
    created = await manager.create_task(ctx, make_task(ctx))
    assert await manager.get_task(ctx, created.id) == created
    pending = await claim_all(outbox)
    assert [(row.org_id, row.kind) for row in pending] == [(ctx.org_id, "tasks.task.created")]
    # The event was appended before the publish failed; relaying again is
    # idempotent on the row's id and marks the row done once the bus is back.
    # The row is seconds old, so the sweep's grace is set aside here.
    working = OutboxRelayImpl(
        outbox, events_storage, infra.get_topics(), options=OutboxOptions(grace=timedelta(0))
    )
    assert await working.relay_pending(10) == 1
    assert await claim_all(outbox) == []
    assert [e.seq for e in await events.get_events(ctx, after_seq=0, limit=10)] == [1]


async def test_a_gap_closed_at_float_precision_renumbers_the_open_list(
    manager: TasksManagerImpl, events: EventsManagerImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    # Fifty-odd moves into the same gap halve it down to nothing: the midpoint
    # then equals the anchor, and the (position, id) tie-break would put the
    # moved task before it. The list is renumbered instead, every row that
    # changed is announced, and the order reads as the move meant it.
    ctx = context(Role.MEMBER)
    c = await manager.create_task(ctx, make_task(ctx, "c"))
    b = await manager.create_task(ctx, make_task(ctx, "b"))
    a = await manager.create_task(ctx, make_task(ctx, "a"))
    await move(manager, ctx, a.id, after_id=b.id)
    moved, expected, moves = a, ["b", "a", "c"], 0
    while [t.position for t in await open_page(manager, ctx)] != [0.0, 1.0, 2.0]:
        moved, expected = (c, ["b", "c", "a"]) if moved is a else (a, ["b", "a", "c"])
        await move(manager, ctx, moved.id, after_id=b.id)
        assert await open_titles(manager, ctx, TaskScope.TEAM) == expected
        moves += 1
        assert moves < 200, "the gap never closed"
    assert 40 < moves < 120, "a gap of one closes after fifty-odd halvings"
    # The renumbering is a write per task whose position changed, each announced
    # and recorded like any update, with nothing left pending in the outbox.
    # Every one of the three moved to a whole number, so it is the last three.
    recorded = await events.get_events(ctx, after_seq=0, limit=1000)
    renumbering = recorded[-3:]
    assert {e.target_id for e in renumbering} == {a.id, b.id, c.id}
    assert all(e.kind == "tasks.task.updated" for e in renumbering)
    assert await claim_all(outbox) == []
    # Halving starts afresh from whole numbers, so the next moves stay ordered.
    for _ in range(10):
        await move(manager, ctx, c.id, after_id=b.id)
        assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b", "c", "a"]
        await move(manager, ctx, a.id, after_id=b.id)
        assert await open_titles(manager, ctx, TaskScope.TEAM) == ["b", "a", "c"]


async def test_a_move_after_a_tied_anchor_lands_between_the_two(
    manager: TasksManagerImpl,
) -> None:
    """Two open tasks can hold the same position: two creates that read the
    same list land on it, and so do two moves after the same last anchor. The
    list orders a tie by id, so "after x" where x ties with y must not put the
    task behind y. There is no position between them, so the list renumbers."""
    ctx = context(Role.MEMBER)
    x = await manager.create_task(ctx, make_task(ctx, "x"))
    y = await manager.create_task(ctx, make_task(ctx, "y"))
    z = await manager.create_task(ctx, make_task(ctx, "z"))
    # x and y tie on the position two concurrent creates would both have read;
    # the list reads them by id, and z sits below both.
    storage = manager._storage  # type: ignore[attr-defined]

    async def place(task: Task, position: float) -> None:
        moved = task.model_copy(update={"position": position, "version": task.version + 1})
        await storage.update_tasks(ctx.org_id, [(moved, task.version, (_row(ctx, moved),))])

    for task in (x, y):
        await place(task, 5.0)
    await place(z, 6.0)
    first, second = sorted((x, y), key=lambda t: t.id)
    assert await open_titles(manager, ctx, TaskScope.TEAM) == [first.title, second.title, "z"]

    w = await manager.create_task(ctx, make_task(ctx, "w"))  # at the top
    await move(manager, ctx, w.id, after_id=first.id)
    assert await open_titles(manager, ctx, TaskScope.TEAM) == [
        first.title,
        "w",
        second.title,
        "z",
    ]
    # The tie is gone: the renumber gave every open task a position of its own.
    positions = [t.position for t in await open_page(manager, ctx)]
    assert positions == sorted(set(positions))


async def test_an_anchor_that_leaves_the_list_mid_move_is_a_failed_precondition(
    manager: TasksManagerImpl,
) -> None:
    """The anchor is read, then the open list is read to renumber around it. A
    delete or a "mark done" of the anchor in between leaves the renumber with
    nothing to follow: that is the caller's snapshot gone stale, answered as
    such, not a StopIteration inside a coroutine that ends as a 500."""
    ctx = context(Role.MEMBER)
    anchor = await manager.create_task(ctx, make_task(ctx, "anchor"))
    task = await manager.create_task(ctx, make_task(ctx, "task"))
    every_open = manager._every_open_task  # type: ignore[attr-defined]

    async def without_the_anchor(inner_ctx: OpContext) -> list[Task]:
        return [t for t in await every_open(inner_ctx) if t.id != anchor.id]

    manager._every_open_task = without_the_anchor  # type: ignore[attr-defined]
    current = await manager.get_task(ctx, task.id)
    with pytest.raises(PreconditionFailed):
        await manager._renumber(ctx, current, anchor, current.version)  # type: ignore[attr-defined]


async def test_the_sweep_purges_only_deleted_tasks_while_the_tenant_lives(
    manager: TasksManagerImpl, members: Members
) -> None:
    org = make_org()
    ctx = context(Role.MEMBER, org, members)
    live = await manager.create_task(ctx, make_task(ctx, "still open"))
    dropped = await delete(manager, ctx, (await manager.create_task(ctx, make_task(ctx, "go"))).id)
    assert await manager.purge_deleted(ctx) == 0, "the retention has not passed"
    past = TasksManagerImpl(
        manager._storage,  # type: ignore[attr-defined]
        members,
        manager._relay,  # type: ignore[attr-defined]
        TasksOptions(retention=timedelta(0)),
        entitlements=ON_TEAM,
    )
    assert await past.purge_deleted(ctx) == 1
    assert (await manager.get_task(ctx, live.id)).id == live.id
    with pytest.raises(NotFound):
        await manager.get_task(ctx, dropped.id)


async def test_a_deleted_tenants_tasks_all_go_once_the_retention_has_passed(
    manager: TasksManagerImpl, members: Members
) -> None:
    """A tenant past its retention keeps its org row and nothing else. Its open
    and done tasks were never soft-deleted, so a purge that reads `deleted_at`
    leaves every one of them behind; the tenant's purge takes them all, and
    another tenant's tasks stay."""
    org = make_org()
    ctx = context(Role.MEMBER, org, members)
    still_open = await manager.create_task(ctx, make_task(ctx, "still open"))
    done = await manager.create_task(ctx, make_task(ctx, "done"))
    await manager.update_task(
        ctx, done.model_copy(update={"status": TaskStatus.DONE}), done.version
    )
    elsewhere = context(Role.MEMBER, make_org(), members)
    kept = await manager.create_task(elsewhere, make_task(elsewhere, "another tenant"))

    assert await manager.purge_deleted(ctx) == 0, "no task is deleted in its own right"
    members.expired = True
    assert await manager.purge_deleted(ctx) == 2, "the open task and the done one"
    for task_id in (still_open.id, done.id):
        with pytest.raises(NotFound):
            await manager.get_task(ctx, task_id)
    assert (await manager.get_task(elsewhere, kept.id)).id == kept.id
    assert await manager.purge_deleted(ctx) == 0, "idempotent"


async def test_a_placement_reads_one_place_however_long_the_open_list(
    manager: TasksManagerImpl,
) -> None:
    """Creating, reopening, and moving a task each read one open place, bounded
    in the statement, never the open list; and the order reads as before."""
    ctx = context(Role.MEMBER)
    storage = manager._storage  # type: ignore[attr-defined]
    read = storage.read_open_places
    reads: list[tuple[int, int]] = []

    async def counted(
        org_id: UUID, exclude: UUID | None, after: tuple[float, UUID] | None, limit: int
    ) -> list[tuple[float, UUID]]:
        places = await read(org_id, exclude, after, limit)
        reads.append((limit, len(places)))
        return places

    storage.read_open_places = counted
    tasks = [await manager.create_task(ctx, make_task(ctx, f"t{i}")) for i in range(30)]
    titles = [f"t{i}" for i in reversed(range(30))]
    assert await open_titles(manager, ctx, TaskScope.TEAM) == titles
    await move(manager, ctx, tasks[0].id, after_id=tasks[29].id)
    titles.remove("t0")
    titles.insert(1, "t0")
    assert await open_titles(manager, ctx, TaskScope.TEAM) == titles
    await move(manager, ctx, tasks[29].id, after_id=tasks[1].id)
    titles.remove("t29")
    titles.append("t29")
    assert await open_titles(manager, ctx, TaskScope.TEAM) == titles
    done = await manager.get_task(ctx, tasks[5].id)
    done = await manager.update_task(
        ctx, done.model_copy(update={"status": TaskStatus.DONE}), done.version
    )
    await manager.update_task(
        ctx, done.model_copy(update={"status": TaskStatus.OPEN}), done.version
    )
    titles.remove("t5")
    titles.insert(0, "t5")
    assert await open_titles(manager, ctx, TaskScope.TEAM) == titles
    assert len(reads) == 30 + 2 + 1
    assert all(limit == 1 and returned <= 1 for limit, returned in reads)
