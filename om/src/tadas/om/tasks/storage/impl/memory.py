from datetime import datetime
from uuid import UUID

from tadas.om.outbox.storage import OutboxLandingInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable
from tadas.om.tasks.rules import is_before, is_visible
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.filter import TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskStatus


class TasksStorageMemoryImpl(MemoryStorageBase, TasksStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._tasks: MemoryTable[Task] = {}

    def _live(self, org_id: UUID, status: TaskStatus) -> list[Task]:
        return [
            t
            for t in self._rows(self._tasks, org_id)
            if t.deleted_at is None and t.status == status
        ]

    async def read_open_tasks(self, org_id: UUID, criterion: TaskFilter, limit: int) -> list[Task]:
        tasks = [t for t in self._live(org_id, TaskStatus.OPEN) if is_visible(t, criterion)]
        return sorted(tasks, key=lambda t: (t.position, t.id))[:limit]

    async def read_done_tasks(
        self, org_id: UUID, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> list[Task]:
        tasks = [
            t
            for t in self._live(org_id, TaskStatus.DONE)
            if is_visible(t, criterion) and (before is None or is_before(t, before))
        ]
        return sorted(tasks, key=lambda t: (t.updated_at, t.id), reverse=True)[:limit]

    async def read_open_positions(self, org_id: UUID, exclude: UUID | None) -> list[float]:
        return sorted(t.position for t in self._live(org_id, TaskStatus.OPEN) if t.id != exclude)

    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None:
        return self._get(self._tasks, org_id, task_id)

    async def purge_deleted(self, org_id: UUID, before: datetime) -> int:
        gone = [
            t.id
            for t in self._rows(self._tasks, org_id)
            if t.deleted_at is not None and t.deleted_at < before
        ]
        for task_id in gone:
            del self._tasks[task_id]
        return len(gone)

    async def write_task(
        self, org_id: UUID, task: Task, outbox_row: OutboxRow | None = None
    ) -> None:
        self._put(self._tasks, org_id, task, outbox_row)
