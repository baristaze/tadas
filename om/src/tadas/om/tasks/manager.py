"""The tasks swimlane: the to-do items a team creates, works, and closes."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.opcontext import OpContext
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.page import TaskPage
from tadas.om.tasks.types.task import Task


class TasksManagerInterface(ABC):
    @abstractmethod
    async def get_open_tasks(
        self, ctx: OpContext, criterion: TaskFilter, after: OpenTaskCursor | None, limit: int
    ) -> TaskPage:
        """One page of the open tasks the filter shows, in manual order, top
        first, strictly after the cursor. The filter's user is the caller:
        `mine` is about nobody else. `limit` is clamped; `has_more` says
        whether a page follows, whatever the clamp did."""
        ...

    @abstractmethod
    async def get_done_tasks(
        self, ctx: OpContext, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> TaskPage:
        """One page of the done tasks the filter shows, newest first, strictly
        before the cursor; `limit` and `has_more` as on `get_open_tasks`."""
        ...

    @abstractmethod
    async def get_task(self, ctx: OpContext, task_id: UUID) -> Task: ...

    @abstractmethod
    async def create_task(self, ctx: OpContext, task: Task) -> Task:
        """A new task is open and goes to the top of the open list."""
        ...

    @abstractmethod
    async def update_task(self, ctx: OpContext, task: Task) -> Task:
        """A task reopened from done goes back to the top of the open list. The
        entity's `version` is the one the caller read: the write lands only
        when the stored task is still at it, and is `VersionMismatch`, a
        `Conflict`, when another writer landed since."""
        ...

    @abstractmethod
    async def move_task(
        self, ctx: OpContext, task_id: UUID, after_id: UUID | None, version: int
    ) -> Task:
        """Places an open task right after `after_id` in the open list, or at
        the top when it is None. `version` is the one the caller read, as on
        `update_task`."""
        ...

    @abstractmethod
    async def delete_task(self, ctx: OpContext, task_id: UUID, version: int) -> Task:
        """The soft delete. `version` is the one the caller read, as on
        `update_task`: a delete that raced an edit is refused, and an edit that
        raced a delete finds the task gone and cannot bring it back."""
        ...

    @abstractmethod
    async def purge_deleted(self, ctx: OpContext) -> int:
        """The sweep, for one tenant: hard-deletes tasks soft-deleted longer ago than
        the retention period; returns how many. The one hard delete."""
        ...
