from collections.abc import Awaitable, Callable
from uuid import UUID

from tadas.om.context import Permission, TenantContext
from tadas.om.exceptions import NotFound
from tadas.om.media import MediaManagerInterface
from tadas.om.media.types.file import File, FilePurpose
from tadas.om.media.types.page import FilePage
from tadas.om.tasks.attachments import TasksAttachmentsManagerInterface
from tadas.om.tasks.types.task import Task


class TasksAttachmentsManagerImpl(TasksAttachmentsManagerInterface):
    def __init__(
        self,
        media: MediaManagerInterface,
        *,
        get_task: Callable[[TenantContext, UUID], Awaitable[Task]],
    ) -> None:
        self._media = media
        # The manager's read of a live task, as a callable: the manager
        # holds this delegate, so the root passes the one operation instead
        # of the manager.
        self._get_task = get_task

    async def attach_file(self, ctx: TenantContext, task_id: UUID, file: File) -> File:
        ctx.require(Permission.WRITE)
        await self._get_task(ctx, task_id)  # a live task of this tenant, or NotFound
        attached = file.model_copy(
            update={"purpose": FilePurpose.TASK_ATTACHMENT, "subject_id": task_id}
        )
        return await self._media.create_file(ctx, attached)

    async def get_attachments(
        self, ctx: TenantContext, task_id: UUID, after: UUID | None, limit: int
    ) -> FilePage:
        await self._get_task(ctx, task_id)
        return await self._media.get_files(ctx, FilePurpose.TASK_ATTACHMENT, task_id, after, limit)

    async def remove_attachment(self, ctx: TenantContext, task_id: UUID, file_id: UUID) -> File:
        ctx.require(Permission.WRITE)
        await self._get_task(ctx, task_id)
        file = await self._media.get_file(ctx, file_id)
        if file.purpose is not FilePurpose.TASK_ATTACHMENT or file.subject_id != task_id:
            raise NotFound(f"file {file_id} is not attached to task {task_id}")
        return await self._media.delete_file(ctx, file_id)
