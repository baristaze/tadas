"""Storage of the tasks swimlane. Every operation takes org_id first; deleted
tasks never appear in a list. The filter and the cursor arrive as the value
objects the manager received, unchanged."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from tadas.om.outbox.types.row import OutboxRow
from tadas.om.tasks.types.filter import TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task


class TasksStorageInterface(ABC):
    @abstractmethod
    async def read_open_tasks(self, org_id: UUID, criterion: TaskFilter, limit: int) -> list[Task]:
        """Open tasks the filter shows (tasks.rules.is_visible), by position, then id."""
        ...

    @abstractmethod
    async def read_done_tasks(
        self, org_id: UUID, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> list[Task]:
        """Done tasks the filter shows, newest first by (updated_at, id), strictly
        before the cursor (tasks.rules.is_before)."""
        ...

    @abstractmethod
    async def read_open_positions(self, org_id: UUID, exclude: UUID | None) -> list[float]:
        """Every open task's position in the org, ascending; the neighbours a
        placement needs, whatever list the caller was looking at."""
        ...

    @abstractmethod
    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None: ...

    @abstractmethod
    async def purge_deleted(self, org_id: UUID, before: datetime) -> int:
        """The one hard delete: removes the tenant's tasks soft-deleted before
        `before`; returns how many."""
        ...

    @abstractmethod
    async def write_task(
        self, org_id: UUID, task: Task, outbox_row: OutboxRow | None = None
    ) -> None:
        """Lands the task and its outbox row together (the named atomic write)."""
        ...
