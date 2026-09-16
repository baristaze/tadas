import pytest

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import TenantMismatch
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.task import Task


def make_task(title: str = "Write the contract") -> Task:
    now = utcnow()
    return Task(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        title=title,
        notes="",
        status="open",
    )


class TaskStorageContract:
    @pytest.fixture
    def storage(self) -> TasksStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_round_trip_and_update_by_copy(self, storage: TasksStorageInterface) -> None:
        org = new_id()
        task = make_task()
        await storage.write_task(org, task)
        assert await storage.read_task(org, task.id) == task
        done = task.model_copy(update={"status": "done", "updated_at": utcnow()})
        await storage.write_task(org, done)
        assert await storage.read_task(org, task.id) == done
        assert await storage.read_tasks(org, limit=10) == [done]

    async def test_reads_are_tenant_scoped(self, storage: TasksStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        task = make_task()
        await storage.write_task(org_a, task)
        assert await storage.read_task(org_b, task.id) is None
        assert await storage.read_tasks(org_b, limit=10) == []

    async def test_write_refuses_another_tenant(self, storage: TasksStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        task = make_task()
        await storage.write_task(org_a, task)
        with pytest.raises(TenantMismatch):
            await storage.write_task(org_b, task.model_copy(update={"title": "Stolen"}))
        assert await storage.read_task(org_a, task.id) == task

    async def test_feed_sorts_by_id_hides_deleted_and_clamps(
        self, storage: TasksStorageInterface
    ) -> None:
        org = new_id()
        tasks = [make_task(f"t{i}") for i in range(3)]
        for task in reversed(tasks):
            await storage.write_task(org, task)
        assert await storage.read_tasks(org, limit=10) == sorted(tasks, key=lambda t: t.id)
        assert len(await storage.read_tasks(org, limit=2)) == 2
        gone = tasks[0].model_copy(update={"deleted_at": utcnow(), "deleted_by": new_id()})
        await storage.write_task(org, gone)
        assert [t.id for t in await storage.read_tasks(org, limit=10)] == [t.id for t in tasks[1:]]
        assert await storage.read_task(org, gone.id) == gone
