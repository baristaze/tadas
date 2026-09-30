"""The attachments duty of the tasks manager: the files kept with a task."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.context import TenantContext
from tadas.om.media.types.file import File
from tadas.om.media.types.page import FilePage


class TasksAttachmentsManagerInterface(ABC):
    """A delegate of `TasksManagerInterface`, reached as `tasks.attachments`.
    Every operation takes `TenantContext`."""

    @abstractmethod
    async def attach_file(self, ctx: TenantContext, task_id: UUID, file: File) -> File:
        """Starts an upload of a file to a live task: the media namespace lands
        it pending, as a task attachment whose subject is the task, whatever
        purpose and subject the caller's file names. The bytes and the confirm
        go through the media namespace."""
        ...

    @abstractmethod
    async def get_attachments(
        self, ctx: TenantContext, task_id: UUID, after: UUID | None, limit: int
    ) -> FilePage:
        """One page of a live task's stored attachments, oldest first."""
        ...

    @abstractmethod
    async def remove_attachment(self, ctx: TenantContext, task_id: UUID, file_id: UUID) -> File:
        """Soft-deletes one attachment of a live task. A file that is not this
        task's attachment is `NotFound`, as one that never existed is."""
        ...
