from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from tadas.om.exceptions import PreconditionFailed, TenantMismatch
from tadas.om.outbox.storage import OutboxLandingInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable
from tadas.om.tasks.rules import Place, follows, is_after, is_before, is_visible
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
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

    async def read_open_tasks(
        self, org_id: UUID, criterion: TaskFilter, after: OpenTaskCursor | None, limit: int
    ) -> list[Task]:
        tasks = [
            t
            for t in self._live(org_id, TaskStatus.OPEN)
            if is_visible(t, criterion) and (after is None or is_after(t, after))
        ]
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

    async def read_open_places(
        self, org_id: UUID, exclude: UUID | None, after: Place | None, limit: int
    ) -> list[Place]:
        places = [
            (t.position, t.id) for t in self._live(org_id, TaskStatus.OPEN) if t.id != exclude
        ]
        return sorted(p for p in places if after is None or follows(p, after))[:limit]

    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None:
        return self._get(self._tasks, org_id, task_id)

    async def count_created_since(self, since: datetime) -> int:
        return sum(1 for task in self._every(self._tasks) if task.created_at >= since)

    async def purge_deleted(self, org_id: UUID, before: datetime) -> int:
        gone = [
            t.id
            for t in self._rows(self._tasks, org_id)
            if t.deleted_at is not None and t.deleted_at < before
        ]
        for task_id in gone:
            del self._tasks[task_id]
        return len(gone)

    async def purge_tenant(self, org_id: UUID) -> int:
        gone = [t.id for t in self._rows(self._tasks, org_id)]
        for task_id in gone:
            del self._tasks[task_id]
        return len(gone)

    async def create_task(
        self, org_id: UUID, task: Task, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._tasks, org_id, task, outbox_rows)

    async def update_task(
        self, org_id: UUID, task: Task, expected_version: int, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        await self.update_tasks(org_id, [(task, expected_version, outbox_rows)])

    async def update_tasks(
        self, org_id: UUID, updates: Sequence[tuple[Task, int, tuple[OutboxRow, ...]]]
    ) -> None:
        # Every check, then every write, one step under the lock, as the
        # conditional statements share one transaction in Postgres.
        async with self._lock:
            for task, expected_version, _ in updates:
                found = self._tasks.get(task.id)
                if found is None:
                    raise PreconditionFailed(f"task {task.id} is gone")
                if found[0] != org_id:
                    raise TenantMismatch(f"{task.id} is not in {org_id}")
                if found[1].version != expected_version:
                    raise PreconditionFailed(
                        f"task {task.id} is at version {found[1].version}, not {expected_version}"
                    )
            for task, _, outbox_rows in updates:
                self._put(self._tasks, org_id, task, outbox_rows)

    async def mark_reminded(
        self,
        org_id: UUID,
        task_id: UUID,
        remind_at: datetime,
        reminded_at: datetime,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> Task | None:
        async with self._lock:
            task = self._get(self._tasks, org_id, task_id)
            if (
                task is None
                or task.status != TaskStatus.OPEN
                or task.deleted_at is not None
                or task.remind_at != remind_at
                or task.reminded_at is not None
            ):
                return None
            written = task.model_copy(
                update={"reminded_at": reminded_at, "version": task.version + 1}
            )
            self._put(self._tasks, org_id, written, outbox_rows)
            return written
