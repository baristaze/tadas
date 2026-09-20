from datetime import timedelta
from uuid import UUID

import pytest

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import TenantMismatch, VersionMismatch
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus


def team() -> TaskFilter:
    return TaskFilter(scope=TaskScope.TEAM, user_id=new_id())


def mine(user_id: UUID) -> TaskFilter:
    return TaskFilter(scope=TaskScope.MINE, user_id=user_id)


def after(task: Task) -> TaskCursor:
    return TaskCursor(updated_at=task.updated_at, id=task.id)


def past(task: Task) -> OpenTaskCursor:
    return OpenTaskCursor(position=task.position, id=task.id)


def make_row(org_id: UUID, task: Task, action: str = "created") -> OutboxRow:
    """The outbox row a write lands with; the memory outbox the root wires
    receives it, the Postgres one inserts it in the same commit."""
    return OutboxRow(
        id=new_id(),
        created_at=utcnow(),
        kind=f"tasks.task.{action}",
        target_id=task.id,
        payload={"title": task.title},
        actor_id=task.created_by,
        request_id=new_id(),
        app="api",
    )


async def seed(storage: TasksStorageInterface, org_id: UUID, task: Task) -> None:
    """Lands a task the way the manager does: through the create primitive.
    An update never inserts, so there is no other way in."""
    assert await storage.create_task(org_id, task, make_row(org_id, task)) is True


async def bump(storage: TasksStorageInterface, org_id: UUID, task: Task, **changes: object) -> Task:
    """The manager's copy on update, at the storage: the next version, written
    against the one the task carries."""
    changed = task.model_copy(update={**changes, "version": task.version + 1})
    await storage.update_task(org_id, changed, task.version, make_row(org_id, changed, "updated"))
    return changed


def make_task(
    title: str = "Write the contract",
    *,
    created_by: UUID | None = None,
    assignee_id: UUID | None = None,
    status: TaskStatus = TaskStatus.OPEN,
    position: float = 0.0,
    updated_ago: timedelta = timedelta(0),
) -> Task:
    now = utcnow()
    return Task(
        id=new_id(),
        created_at=now,
        updated_at=now - updated_ago,
        created_by=created_by or new_id(),
        updated_by=created_by or new_id(),
        title=title,
        status=status,
        assignee_id=assignee_id,
        position=position,
    )


class TaskStorageContract:
    @pytest.fixture
    def storage(self) -> TasksStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_round_trip_and_update_by_copy(self, storage: TasksStorageInterface) -> None:
        org = new_id()
        task = make_task(assignee_id=new_id(), position=-2.5)
        await seed(storage, org, task)
        assert await storage.read_task(org, task.id) == task
        done = await bump(storage, org, task, status=TaskStatus.DONE, updated_at=utcnow())
        assert await storage.read_task(org, task.id) == done
        assert await storage.read_open_tasks(org, team(), None, limit=10) == []
        assert await storage.read_done_tasks(org, team(), None, limit=10) == [done]

    async def test_create_reports_an_existing_id_and_changes_nothing(
        self, storage: TasksStorageInterface
    ) -> None:
        # The create primitive: a retry presents the id it minted the first time;
        # the insert reports it, and neither the row nor the outbox is touched.
        org_id = new_id()
        task = make_task("Once")
        assert await storage.create_task(org_id, task, make_row(org_id, task)) is True
        again = task.model_copy(update={"title": "Twice"})
        assert await storage.create_task(org_id, again, make_row(org_id, again)) is False
        stored = await storage.read_task(org_id, task.id)
        assert stored is not None and stored.title == "Once"

    async def test_reads_are_tenant_scoped(self, storage: TasksStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        task = make_task()
        await seed(storage, org_a, task)
        assert await storage.read_task(org_b, task.id) is None
        assert await storage.read_open_tasks(org_b, team(), None, limit=10) == []
        assert await storage.read_open_positions(org_b, exclude=None) == []

    async def test_write_refuses_another_tenant(self, storage: TasksStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        task = make_task()
        await seed(storage, org_a, task)
        with pytest.raises(TenantMismatch):
            await bump(storage, org_b, task, title="Stolen")
        assert await storage.read_task(org_a, task.id) == task

    async def test_update_is_a_compare_and_set_on_the_version(
        self, storage: TasksStorageInterface
    ) -> None:
        # Two writers read the task at version 1. The first lands at version 2;
        # the second still names version 1, so the row has moved under it and
        # the write is refused with nothing changed, not merged over the first.
        org = new_id()
        task = make_task("as read")
        await seed(storage, org, task)
        first = await bump(storage, org, task, title="first writer")
        with pytest.raises(VersionMismatch):
            await bump(storage, org, task, title="second writer")
        assert await storage.read_task(org, task.id) == first
        assert first.version == 2
        # The winner's snapshot is current, so the next write from it lands.
        second = await bump(storage, org, first, title="first writer again")
        assert (await storage.read_task(org, task.id)) == second and second.version == 3

    async def test_update_never_inserts_a_missing_row(self, storage: TasksStorageInterface) -> None:
        # A row that is gone (purged between the read and the write) has moved
        # too: the update reports it and leaves nothing behind.
        org = new_id()
        task = make_task("never stored")
        with pytest.raises(VersionMismatch):
            await bump(storage, org, task, title="conjured")
        assert await storage.read_task(org, task.id) is None

    async def test_open_list_sorts_by_position_hides_deleted_and_clamps(
        self, storage: TasksStorageInterface
    ) -> None:
        org = new_id()
        tasks = [make_task(f"t{i}", position=float(p)) for i, p in enumerate([3, -1, 2])]
        for task in tasks:
            await seed(storage, org, task)
        listed = await storage.read_open_tasks(org, team(), None, limit=10)
        assert [t.title for t in listed] == ["t1", "t2", "t0"]
        assert len(await storage.read_open_tasks(org, team(), None, limit=2)) == 2
        assert await storage.read_open_positions(org, exclude=None) == [-1.0, 2.0, 3.0]
        assert await storage.read_open_positions(org, exclude=tasks[1].id) == [2.0, 3.0]
        gone = await bump(storage, org, tasks[1], deleted_at=utcnow(), deleted_by=new_id())
        assert [t.title for t in await storage.read_open_tasks(org, team(), None, limit=10)] == [
            "t2",
            "t0",
        ]
        assert await storage.read_task(org, gone.id) == gone

    async def test_open_list_pages_by_position_cursor(self, storage: TasksStorageInterface) -> None:
        # Two tasks share a position (a seed, or a float that met its limit):
        # the id breaks the tie, in the list and in the cursor alike.
        org = new_id()
        tasks = [make_task(f"o{i}", position=float(p)) for i, p in enumerate([1, 2, 2, 3, 4])]
        for task in tasks:
            await seed(storage, org, task)
        first = await storage.read_open_tasks(org, team(), None, limit=2)
        second = await storage.read_open_tasks(org, team(), past(first[-1]), limit=2)
        third = await storage.read_open_tasks(org, team(), past(second[-1]), limit=2)
        assert [t.id for t in [*first, *second, *third]] == [
            t.id for t in sorted(tasks, key=lambda t: (t.position, t.id))
        ]
        assert await storage.read_open_tasks(org, team(), past(third[-1]), limit=2) == []

    async def test_done_list_is_newest_first_and_pages_by_cursor(
        self, storage: TasksStorageInterface
    ) -> None:
        org = new_id()
        tasks = [
            make_task(f"d{i}", status=TaskStatus.DONE, updated_ago=timedelta(minutes=i))
            for i in range(5)
        ]
        for task in reversed(tasks):
            await seed(storage, org, task)
        first = await storage.read_done_tasks(org, team(), None, limit=2)
        assert [t.title for t in first] == ["d0", "d1"]
        second = await storage.read_done_tasks(org, team(), after(first[-1]), limit=2)
        assert [t.title for t in second] == ["d2", "d3"]
        third = await storage.read_done_tasks(org, team(), after(second[-1]), limit=2)
        assert [t.title for t in third] == ["d4"]

    async def test_mine_is_assigned_to_me_or_unassigned_and_created_by_me(
        self, storage: TasksStorageInterface
    ) -> None:
        org, me, other = new_id(), new_id(), new_id()
        mine_created = make_task("created by me", created_by=me, position=1)
        mine_assigned = make_task("assigned to me", created_by=other, assignee_id=me, position=2)
        given_away = make_task("created by me, assigned away", created_by=me, assignee_id=other)
        theirs = make_task("theirs", created_by=other, position=3)
        mine_done = make_task("mine, done", created_by=me, status=TaskStatus.DONE)
        for task in (mine_created, mine_assigned, given_away, theirs, mine_done):
            await seed(storage, org, task)
        assert [t.title for t in await storage.read_open_tasks(org, mine(me), None, limit=10)] == [
            "created by me",
            "assigned to me",
        ]
        assert len(await storage.read_open_tasks(org, team(), None, limit=10)) == 4
        assert [t.title for t in await storage.read_done_tasks(org, mine(me), None, limit=10)] == [
            "mine, done"
        ]
        assert await storage.read_done_tasks(org, mine(other), None, limit=10) == []

    async def test_purge_removes_only_tasks_deleted_before_the_cut(
        self, storage: TasksStorageInterface
    ) -> None:
        org, elsewhere = new_id(), new_id()
        old, recent, live = make_task("old"), make_task("recent"), make_task("live")
        cut = utcnow()
        await seed(
            storage,
            org,
            old.model_copy(update={"deleted_at": cut - timedelta(days=1), "deleted_by": org}),
        )
        await seed(storage, org, recent.model_copy(update={"deleted_at": cut, "deleted_by": org}))
        await seed(storage, org, live)
        other = make_task("other")
        await seed(
            storage, elsewhere, other.model_copy(update={"deleted_at": cut - timedelta(days=1)})
        )
        assert await storage.purge_deleted(org, cut) == 1
        assert await storage.read_task(org, old.id) is None
        assert await storage.read_task(org, recent.id) is not None
        assert await storage.read_task(org, live.id) == live
        assert await storage.read_task(elsewhere, other.id) is not None, "per tenant"
        assert await storage.purge_deleted(org, cut) == 0, "idempotent"

    async def test_many_updates_land_together_or_not_at_all(
        self, storage: TasksStorageInterface
    ) -> None:
        # The renumbering of an open list: every row against its own version, in
        # one commit. One stale version refuses the whole write, so a list is
        # never renumbered halfway; from current versions every row lands.
        org = new_id()
        first, second = make_task("first", position=0.5), make_task("second", position=0.75)
        await seed(storage, org, first)
        await seed(storage, org, second)
        moved_second = await bump(storage, org, second, title="moved")  # now at version 2

        def placed(task: Task, position: float) -> Task:
            return task.model_copy(update={"position": position, "version": task.version + 1})

        with pytest.raises(VersionMismatch):
            await storage.update_tasks(
                org,
                [
                    (placed(first, 0.0), first.version, make_row(org, first, "updated")),
                    (placed(second, 1.0), second.version, make_row(org, second, "updated")),
                ],
            )
        assert await storage.read_task(org, first.id) == first
        assert await storage.read_task(org, second.id) == moved_second
        renumbered = [placed(first, 0.0), placed(moved_second, 1.0)]
        await storage.update_tasks(
            org,
            [
                (renumbered[0], first.version, make_row(org, first, "updated")),
                (renumbered[1], moved_second.version, make_row(org, second, "updated")),
            ],
        )
        assert await storage.read_task(org, first.id) == renumbered[0]
        assert await storage.read_task(org, second.id) == renumbered[1]
        assert await storage.read_open_positions(org, exclude=None) == [0.0, 1.0]
