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
    async def count_open_tasks(self, org_id: UUID, criterion: TaskFilter) -> int:
        """How many open tasks the filter shows (tasks.rules.is_visible): a
        number, never the rows, for a caller that shows a page and says how
        many more there are."""
        ...

    @abstractmethod
    async def read_done_tasks(
        self, org_id: UUID, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> list[Task]:
        """Done tasks the filter shows, newest first by (updated_at, id), strictly
        before the cursor (tasks.rules.is_before)."""
        ...

    @abstractmethod
    async def read_open_places(
        self, org_id: UUID, exclude: UUID | None, after: Place | None, limit: int
    ) -> list[Place]:
        """Open tasks' places in the org — their (position, id) — ascending in
        the order the open list reads, strictly after `after` when one is given
        (tasks.rules.follows), at most `limit` of them; the neighbours a
        placement needs, whatever list the caller was looking at. The id rides
        along because a position is not unique (tasks.rules.Place). The caller
        picks the bound: a placement asks for the one place it reads."""
        ...

    @abstractmethod
    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None: ...

    @abstractmethod
    async def count_created_since(self, since: datetime) -> int:
        """Global: how many tasks were created at or after `since`, across every
        tenant and whatever became of them since; the traffic the operator
        plane's size reads."""
        ...

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
    async def create_task(
        self, org_id: UUID, task: Task, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create: lands the task and the rows that announce it together, or
        neither when the id is already written, which it reports as False. An
        entity change is one row; a create that also starts work passes a second
        row of kind `work.<kind>` in the same tuple, because the queue is a role
        of its own and no statement reaches both."""
        ...

    @abstractmethod
    async def update_task(
        self, org_id: UUID, task: Task, expected_version: int, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        """The update, a compare-and-set: lands the task and its outbox rows
        together (the named atomic write) when the stored row is at
        `expected_version`, and raises `PreconditionFailed` when it is at another
        version or is gone, landing nothing. It never inserts: a missing row is
        a row that moved."""
        ...

    @abstractmethod
    async def update_tasks(
        self, org_id: UUID, updates: Sequence[tuple[Task, int, tuple[OutboxRow, ...]]]
    ) -> None:
        """The same compare-and-set over many tasks: every task lands with its
        outbox rows, each against its own expected version, in one commit, or
        none does and `PreconditionFailed` is raised. The renumbering of an open
        list is this write: a list renumbered halfway is out of order."""
        ...

    @abstractmethod
    async def mark_reminded(
        self,
        org_id: UUID,
        task_id: UUID,
        remind_at: datetime,
        reminded_at: datetime,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> Task | None:
        """The reminder's compare-and-set, one conditional write: stamps
        `reminded_at` and moves the version on while the task is open, not
        deleted, still due at `remind_at`, and not yet reminded, and lands the
        rows that announce it in the same commit. Returns the task as written,
        or None when any of the four no longer holds, landing nothing: a
        reminder for a moved, cleared, or finished due time, and a second run
        of one that went out, write nothing."""
        ...
