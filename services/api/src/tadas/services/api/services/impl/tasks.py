import base64
from datetime import datetime
from uuid import UUID

from tadas.om.base import utcnow
from tadas.om.exceptions import ValidationFailed
from tadas.om.opcontext import OpContext
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.page import TaskPage
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus
from tadas.services.api.services.tasks import TasksServiceInterface
from tadas.services.api.types.common import clamp_limit
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
        )
        return TaskView.model_validate(await self._tasks.create_task(ctx, task))

    async def update_task(self, ctx: OpContext, task_id: UUID, body: UpdateTaskRequest) -> TaskView:
        current = await self._tasks.get_task(ctx, task_id)
        # Only the assignee can be cleared; a null title, notes, or status is
        # ignored. The version is the caller's, never the stored one: the
        # manager conditions the write on it.
        changes = {
            name: value
            for name, value in body.model_dump(exclude_unset=True).items()
            if value is not None or name == "assignee_id"
        }
        # model_copy does not validate; a copy that carries caller input does.
        changed = Task.model_validate({**current.model_dump(), **changes})
        return TaskView.model_validate(await self._tasks.update_task(ctx, changed))

    async def move_task(self, ctx: OpContext, task_id: UUID, body: MoveTaskRequest) -> TaskView:
        moved = await self._tasks.move_task(ctx, task_id, body.after_id, body.version)
        return TaskView.model_validate(moved)

    async def delete_task(self, ctx: OpContext, task_id: UUID, version: int) -> TaskView:
        return TaskView.model_validate(await self._tasks.delete_task(ctx, task_id, version))
