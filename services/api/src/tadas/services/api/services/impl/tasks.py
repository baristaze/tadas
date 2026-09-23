import base64
from datetime import datetime
from uuid import UUID

from tadas.om.base import utcnow
from tadas.om.exceptions import ValidationFailed
from tadas.om.media.types.file import File, FilePurpose
from tadas.om.opcontext import OpContext
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.page import TaskPage
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus
from tadas.services.api.services.impl.media import file_view
from tadas.services.api.services.tasks import TasksServiceInterface
from tadas.services.api.types.common import clamp_limit
from tadas.services.api.types.media import AddFileRequest, FilePageView, FileView
from tadas.services.api.types.tasks import (
    AddTaskRequest,
    MoveTaskRequest,
    TaskPageView,
    TaskView,
    UpdateTaskRequest,
)


def encode_cursor(status: TaskStatus, task: Task) -> str:
    """Opaque on the wire: the list it belongs to and where its page ended,
    the last task's (position, id) for the open list and (updated_at, id)
    for the done one."""
    mark = repr(task.position) if status == TaskStatus.OPEN else task.updated_at.isoformat()
    raw = f"{status.value}|{mark}|{task.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(status: TaskStatus, cursor: str) -> OpenTaskCursor | TaskCursor:
    """The cursor of the list asked for; one from the other list, or from
    nowhere, is refused."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        issued_for, mark, task_id = raw.split("|")
        if issued_for != status.value:
            raise ValueError(issued_for)
        if status == TaskStatus.OPEN:
            return OpenTaskCursor(position=float(mark), id=UUID(task_id))
        return TaskCursor(updated_at=datetime.fromisoformat(mark), id=UUID(task_id))
    except ValueError:
        raise ValidationFailed("the cursor is not one this list issued") from None


def decode_file_cursor(cursor: str) -> UUID:
    """An attachment page's cursor is the id the previous page ended on."""
    try:
        return UUID(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode())
    except ValueError:
        raise ValidationFailed("the cursor is not one this list issued") from None


def encode_file_cursor(file_id: UUID) -> str:
    return base64.urlsafe_b64encode(str(file_id).encode()).decode().rstrip("=")


def expected_version(named: int | None) -> int:
    """The version a write compares with: the one the request names, in
    `If-Match` or `expected_version`. A request that names none would
    overwrite blind, so it is refused."""
    if named is None:
        raise ValidationFailed("a write names the version it read, in If-Match or expected_version")
    return named


class TasksServiceImpl(TasksServiceInterface):
    def __init__(self, tasks: TasksManagerInterface) -> None:
        self._tasks = tasks

    async def get_tasks(
        self,
        ctx: OpContext,
        status: TaskStatus,
        scope: TaskScope,
        cursor: str | None,
        limit: int,
    ) -> TaskPageView:
        # The public page size is clamped here and again by the manager; the
        # manager's lookahead past it is what makes `has_more` true.
        limit = clamp_limit(limit)
        criterion = TaskFilter(scope=scope, user_id=ctx.user_id)
        page: TaskPage
        if status == TaskStatus.OPEN:
            after = decode_cursor(status, cursor) if cursor else None
            assert after is None or isinstance(after, OpenTaskCursor)
            page = await self._tasks.get_open_tasks(ctx, criterion, after, limit)
        else:
            before = decode_cursor(status, cursor) if cursor else None
            assert before is None or isinstance(before, TaskCursor)
            page = await self._tasks.get_done_tasks(ctx, criterion, before, limit)
        return TaskPageView(
            items=[TaskView.model_validate(t) for t in page.items],
            next_cursor=encode_cursor(status, page.items[-1]) if page.has_more else None,
        )

    async def get_task(self, ctx: OpContext, task_id: UUID) -> TaskView:
        return TaskView.model_validate(await self._tasks.get_task(ctx, task_id))

    async def create_task(self, ctx: OpContext, body: AddTaskRequest, task_id: UUID) -> TaskView:
        now = utcnow()
        task = Task(
            id=task_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            title=body.title,
            notes=body.notes,
            assignee_id=body.assignee_id,
            remind_at=body.remind_at,
        )
        return TaskView.model_validate(await self._tasks.create_task(ctx, task))

    async def update_task(
        self, ctx: OpContext, task_id: UUID, body: UpdateTaskRequest, if_match: int | None
    ) -> TaskView:
        expected = expected_version(if_match)
        current = await self._tasks.get_task(ctx, task_id)
        # Only the assignee and the due time can be cleared; a null title,
        # notes, or status is ignored. The version is the caller's, never the stored one, and it
        # travels beside the entity: the manager conditions the write on it.
        changes = {
            name: value
            for name, value in body.model_dump(exclude_unset=True).items()
            if value is not None or name in ("assignee_id", "remind_at")
        }
        # model_copy does not validate; a copy that carries caller input does.
        changed = Task.model_validate({**current.model_dump(), **changes})
        return TaskView.model_validate(await self._tasks.update_task(ctx, changed, expected))

    async def move_task(self, ctx: OpContext, task_id: UUID, body: MoveTaskRequest) -> TaskView:
        expected = expected_version(body.expected_version)
        moved = await self._tasks.move_task(ctx, task_id, body.after_id, expected)
        return TaskView.model_validate(moved)

    async def delete_task(self, ctx: OpContext, task_id: UUID, if_match: int | None) -> TaskView:
        expected = expected_version(if_match)
        return TaskView.model_validate(await self._tasks.delete_task(ctx, task_id, expected))

    async def attach_file(
        self, ctx: OpContext, task_id: UUID, body: AddFileRequest, file_id: UUID
    ) -> FileView:
        now = utcnow()
        file = File(
            id=file_id,
            name=body.name,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
            purpose=FilePurpose.TASK_ATTACHMENT,
            subject_id=task_id,
        )
        return file_view(await self._tasks.attach_file(ctx, task_id, file))

    async def get_attachments(
        self, ctx: OpContext, task_id: UUID, cursor: str | None, limit: int
    ) -> FilePageView:
        after = decode_file_cursor(cursor) if cursor else None
        page = await self._tasks.get_attachments(ctx, task_id, after, clamp_limit(limit))
        return FilePageView(
            items=[file_view(f) for f in page.items],
            next_cursor=encode_file_cursor(page.items[-1].id) if page.has_more else None,
        )

    async def remove_attachment(self, ctx: OpContext, task_id: UUID, file_id: UUID) -> FileView:
        return file_view(await self._tasks.remove_attachment(ctx, task_id, file_id))
