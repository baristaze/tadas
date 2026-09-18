from datetime import timedelta
from uuid import UUID

import pytest

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import TenantMismatch
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.filter import TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus


def team() -> TaskFilter:
    return TaskFilter(scope=TaskScope.TEAM, user_id=new_id())


def mine(user_id: UUID) -> TaskFilter:
    return TaskFilter(scope=TaskScope.MINE, user_id=user_id)


def after(task: Task) -> TaskCursor:
    return TaskCursor(updated_at=task.updated_at, id=task.id)


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
        await storage.write_task(org, task)
        assert await storage.read_task(org, task.id) == task
        done = task.model_copy(update={"status": TaskStatus.DONE, "updated_at": utcnow()})
        await storage.write_task(org, done)
        assert await storage.read_task(org, task.id) == done
        assert await storage.read_open_tasks(org, team(), limit=10) == []
        assert await storage.read_done_tasks(org, team(), None, limit=10) == [done]

    async def test_reads_are_tenant_scoped(self, storage: TasksStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        task = make_task()
        await storage.write_task(org_a, task)
        assert await storage.read_task(org_b, task.id) is None
        assert await storage.read_open_tasks(org_b, team(), limit=10) == []
        assert await storage.read_open_positions(org_b, exclude=None) == []

    async def test_write_refuses_another_tenant(self, storage: TasksStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        task = make_task()
        await storage.write_task(org_a, task)
        with pytest.raises(TenantMismatch):
            await storage.write_task(org_b, task.model_copy(update={"title": "Stolen"}))
        assert await storage.read_task(org_a, task.id) == task

    async def test_open_list_sorts_by_position_hides_deleted_and_clamps(
        self, storage: TasksStorageInterface
    ) -> None:
        org = new_id()
        tasks = [make_task(f"t{i}", position=float(p)) for i, p in enumerate([3, -1, 2])]
        for task in tasks:
            await storage.write_task(org, task)
        listed = await storage.read_open_tasks(org, team(), limit=10)
        assert [t.title for t in listed] == ["t1", "t2", "t0"]
        assert len(await storage.read_open_tasks(org, team(), limit=2)) == 2
        assert await storage.read_open_positions(org, exclude=None) == [-1.0, 2.0, 3.0]
        assert await storage.read_open_positions(org, exclude=tasks[1].id) == [2.0, 3.0]
        gone = tasks[1].model_copy(update={"deleted_at": utcnow(), "deleted_by": new_id()})
        await storage.write_task(org, gone)
        assert [t.title for t in await storage.read_open_tasks(org, team(), limit=10)] == [
            "t2",
            "t0",
        ]
        assert await storage.read_task(org, gone.id) == gone

    async def test_done_list_is_newest_first_and_pages_by_cursor(
        self, storage: TasksStorageInterface
    ) -> None:
        org = new_id()
        tasks = [
            make_task(f"d{i}", status=TaskStatus.DONE, updated_ago=timedelta(minutes=i))
            for i in range(5)
        ]
        for task in reversed(tasks):
            await storage.write_task(org, task)
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
            await storage.write_task(org, task)
        assert [t.title for t in await storage.read_open_tasks(org, mine(me), limit=10)] == [
            "created by me",
            "assigned to me",
        ]
        assert len(await storage.read_open_tasks(org, team(), limit=10)) == 4
        assert [t.title for t in await storage.read_done_tasks(org, mine(me), None, limit=10)] == [
            "mine, done"
        ]
        assert await storage.read_done_tasks(org, mine(other), None, limit=10) == []
