from uuid import UUID

from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.task import Task


class TasksStorageMemoryImpl(MemoryStorageBase, TasksStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._tasks: MemoryTable[Task] = {}

    async def read_tasks(self, org_id: UUID, limit: int) -> list[Task]:
        return [t for t in self._rows(self._tasks, org_id) if t.deleted_at is None][:limit]

    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None:
        return self._get(self._tasks, org_id, task_id)

    async def write_task(self, org_id: UUID, task: Task) -> None:
        self._put(self._tasks, org_id, task)
