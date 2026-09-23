"""The tasks swimlane: the to-do items a team creates, works, and closes."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from tadas.om.media.types.file import File
from tadas.om.media.types.page import FilePage
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
    async def count_open_tasks(self, ctx: OpContext, criterion: TaskFilter) -> int:
        """How many open tasks the filter shows, the number beside a page of
        `get_open_tasks`; the filter's user is the caller, as there."""
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
        """A new task is open and goes to the top of the open list. An org at
        its plan's bound of active tasks is refused (`PlanLimitReached`)."""
        ...

    @abstractmethod
    async def update_task(self, ctx: OpContext, task: Task, expected_version: int) -> Task:
        """A task reopened from done goes back to the top of the open list, and
        is refused like a create when the org is at its bound. The
        entity supplies the fields a caller may change; the provenance and the
        task's `MANAGER_OWNED_FIELDS` stay as stored. `expected_version` is the
        version the caller read, never one read here: the write lands only
        when the stored task is still at it, and is `PreconditionFailed` when
        another writer landed since."""
        ...

    @abstractmethod
    async def move_task(
        self, ctx: OpContext, task_id: UUID, after_id: UUID | None, expected_version: int
    ) -> Task:
        """Places an open task right after `after_id` in the open list, or at
        the top when it is None. `expected_version` is the one the caller
        read, as on `update_task`."""
        ...

    @abstractmethod
    async def delete_task(self, ctx: OpContext, task_id: UUID, expected_version: int) -> Task:
        """The soft delete. `expected_version` is the one the caller read, as
        on `update_task`: a delete that raced an edit is refused, and an edit
        that raced a delete finds the task gone and cannot bring it back. The
        task's attachments are soft-deleted after it, in their own writes."""
        ...

    @abstractmethod
    async def attach_file(self, ctx: OpContext, task_id: UUID, file: File) -> File:
        """Starts an upload of a file to a live task: the media namespace lands
        it pending, as a task attachment whose subject is the task, whatever
        purpose and subject the caller's file names. The bytes and the confirm
        go through the media namespace."""
        ...

    @abstractmethod
    async def get_attachments(
        self, ctx: OpContext, task_id: UUID, after: UUID | None, limit: int
    ) -> FilePage:
        """One page of a live task's stored attachments, oldest first."""
        ...

    @abstractmethod
    async def remove_attachment(self, ctx: OpContext, task_id: UUID, file_id: UUID) -> File:
        """Soft-deletes one attachment of a live task. A file that is not this
        task's attachment is `NotFound`, as one that never existed is."""
        ...

    @abstractmethod
    async def count_active_tasks(self, ctx: OpContext) -> int:
        """How many of the org's tasks are open and not deleted: what the
        plan's active-task bound counts."""
        ...

    @abstractmethod
    async def fire_reminder(
        self, ctx: OpContext, task_id: UUID, remind_at: datetime
    ) -> Task | None:
        """The reminder the task's due time scheduled, when it comes due: marks
        the task reminded and announces it (`tasks.task.reminded`), and asks
        for the Slack post when the org has a channel connected, all in one
        write conditioned on the task still being open and due at `remind_at`
        and not yet reminded. None when it no longer is, which is a reminder
        gone stale: nothing is written and nothing is announced."""
        ...

    @abstractmethod
    async def purge_deleted(self, ctx: OpContext) -> int:
        """The sweep, for one tenant: hard-deletes tasks soft-deleted longer ago than
        the retention period; returns how many. Under a tenant deleted longer
        ago than the retention every task goes, open and done ones too, since
        the tenant keeps nothing but its org row. The one hard delete."""
        ...
