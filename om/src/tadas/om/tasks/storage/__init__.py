"""Storage of the tasks swimlane. Every operation takes org_id first; deleted
tasks never appear in a list. The filter and the cursor arrive as the value
objects the manager received, unchanged."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from tadas.om.outbox.types.row import OutboxRow
from tadas.om.tasks.rules import Place
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task


class TasksStorageInterface(ABC):
    @abstractmethod
    async def read_open_tasks(
        self, org_id: UUID, criterion: TaskFilter, after: OpenTaskCursor | None, limit: int
    ) -> list[Task]:
        """Open tasks the filter shows (tasks.rules.is_visible), by position, then
        id, strictly after the cursor (tasks.rules.is_after). `limit` is the
        caller's: the manager asks for one row more than its page."""
        ...

    @abstractmethod
    async def read_done_tasks(
        self, org_id: UUID, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> list[Task]:
        """Done tasks the filter shows, newest first by (updated_at, id), strictly
        before the cursor (tasks.rules.is_before)."""
        ...

    @abstractmethod
    async def read_open_places(self, org_id: UUID, exclude: UUID | None) -> list[Place]:
        """Every open task's place in the org — its (position, id) — ascending in
        the order the open list reads; the neighbours a placement needs,
        whatever list the caller was looking at. The id rides along because a
        position is not unique (tasks.rules.Place)."""
        ...

    @abstractmethod
    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None: ...

    @abstractmethod
    async def purge_deleted(self, org_id: UUID, before: datetime) -> int:
        """The one hard delete: removes the tenant's tasks soft-deleted before
        `before`; returns how many."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID) -> int:
        """The hard delete of a deleted tenant's tasks once the retention has
        passed: every task of the tenant, whatever its state, since an open or
        a done task is never soft-deleted and `purge_deleted` would leave it
        behind forever; returns how many rows went."""
        ...

    @abstractmethod
    async def create_task(self, org_id: UUID, task: Task, outbox_row: OutboxRow) -> bool:
        """The create: lands the task and its outbox row together, or neither when
        the id is already written, which it reports as False."""
        ...

    @abstractmethod
    async def update_task(
        self, org_id: UUID, task: Task, expected_version: int, outbox_row: OutboxRow
    ) -> None:
        """The update, a compare-and-set: lands the task and its outbox row together
        (the named atomic write) when the stored row is at `expected_version`, and
        raises `VersionMismatch` when it is at another version or is gone, landing
        nothing. It never inserts: a missing row is a row that moved."""
        ...

    @abstractmethod
    async def update_tasks(
        self, org_id: UUID, updates: Sequence[tuple[Task, int, OutboxRow]]
    ) -> None:
        """The same compare-and-set over many tasks: every task lands with its
        outbox row, each against its own expected version, in one commit, or
        none does and `VersionMismatch` is raised. The renumbering of an open
        list is this write: a list renumbered halfway is out of order."""
        ...
