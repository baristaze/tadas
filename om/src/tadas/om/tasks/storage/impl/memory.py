from datetime import datetime
from uuid import UUID

from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.task import Task, TaskStatus


def _visible_to(task: Task, for_user: UUID | None) -> bool:
    if for_user is None:
        return True
    if task.assignee_id is not None:
        return task.assignee_id == for_user
    return task.created_by == for_user


class TasksStorageMemoryImpl(MemoryStorageBase, TasksStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._tasks: MemoryTable[Task] = {}

    def _live(self, org_id: UUID, status: TaskStatus) -> list[Task]:
        return [
            t
            for t in self._rows(self._tasks, org_id)
            if t.deleted_at is None and t.status == status
        ]

    async def read_open_tasks(self, org_id: UUID, for_user: UUID | None, limit: int) -> list[Task]:
        tasks = [t for t in self._live(org_id, TaskStatus.OPEN) if _visible_to(t, for_user)]
        return sorted(tasks, key=lambda t: (t.position, t.id))[:limit]

    async def read_done_tasks(
        self,
        org_id: UUID,
        for_user: UUID | None,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Task]:
        tasks = [
            t
            for t in self._live(org_id, TaskStatus.DONE)
            if _visible_to(t, for_user) and (before is None or (t.updated_at, t.id) < before)
        ]
        return sorted(tasks, key=lambda t: (t.updated_at, t.id), reverse=True)[:limit]

    async def read_open_positions(self, org_id: UUID, exclude: UUID | None) -> list[float]:
        return sorted(t.position for t in self._live(org_id, TaskStatus.OPEN) if t.id != exclude)

    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None:
        return self._get(self._tasks, org_id, task_id)

    async def write_task(self, org_id: UUID, task: Task) -> None:
        self._put(self._tasks, org_id, task)
