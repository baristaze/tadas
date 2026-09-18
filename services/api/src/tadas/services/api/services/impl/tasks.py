import base64
from datetime import datetime
from uuid import UUID

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import ValidationFailed
from tadas.om.opcontext import OpContext
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.types.filter import TaskCursor, TaskFilter
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


def encode_cursor(task: Task) -> str:
    raw = f"{task.updated_at.isoformat()}|{task.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> TaskCursor:
    """The (updated_at, id) of the last task of the previous page."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        updated_at, task_id = raw.split("|")
        return TaskCursor(updated_at=datetime.fromisoformat(updated_at), id=UUID(task_id))
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
        limit = clamp_limit(limit)
        criterion = TaskFilter(scope=scope, user_id=ctx.user_id)
        if status == TaskStatus.OPEN:
            tasks = await self._tasks.get_open_tasks(ctx, criterion, limit)
            return TaskPageView(items=[TaskView.model_validate(t) for t in tasks], next_cursor=None)
        before = decode_cursor(cursor) if cursor else None
        # One more than asked tells whether a next page exists.
        tasks = await self._tasks.get_done_tasks(ctx, criterion, before, limit + 1)
        page, more = tasks[:limit], len(tasks) > limit
        return TaskPageView(
            items=[TaskView.model_validate(t) for t in page],
            next_cursor=encode_cursor(page[-1]) if more and page else None,
        )

    async def get_task(self, ctx: OpContext, task_id: UUID) -> TaskView:
        return TaskView.model_validate(await self._tasks.get_task(ctx, task_id))

    async def create_task(self, ctx: OpContext, body: AddTaskRequest) -> TaskView:
        now = utcnow()
        task = Task(
            id=new_id(),
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
        # Only the assignee can be cleared; a null title, notes, or status is ignored.
        changes = {
            name: value
            for name, value in body.model_dump(exclude_unset=True).items()
            if value is not None or name == "assignee_id"
        }
        # model_copy does not validate; a copy that carries caller input does.
        changed = Task.model_validate({**current.model_dump(), **changes})
        return TaskView.model_validate(await self._tasks.update_task(ctx, changed))

    async def move_task(self, ctx: OpContext, task_id: UUID, body: MoveTaskRequest) -> TaskView:
        return TaskView.model_validate(await self._tasks.move_task(ctx, task_id, body.after_id))

    async def delete_task(self, ctx: OpContext, task_id: UUID) -> TaskView:
        return TaskView.model_validate(await self._tasks.delete_task(ctx, task_id))
