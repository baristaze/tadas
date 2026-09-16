from uuid import UUID

from tadas.om.base import new_id, utcnow
from tadas.om.opcontext import OpContext
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.types.task import Task
from tadas.services.api.services.tasks import TasksServiceInterface
from tadas.services.api.types.common import clamp_limit
from tadas.services.api.types.tasks import AddTaskRequest, TaskView, UpdateTaskRequest


class TasksServiceImpl(TasksServiceInterface):
    def __init__(self, tasks: TasksManagerInterface) -> None:
        self._tasks = tasks

    async def get_tasks(self, ctx: OpContext, limit: int) -> list[TaskView]:
        tasks = await self._tasks.get_tasks(ctx, clamp_limit(limit))
        return [TaskView.model_validate(t) for t in tasks]

    async def get_task(self, ctx: OpContext, task_id: UUID) -> TaskView:
        return TaskView.model_validate(await self._tasks.get_task(ctx, task_id))

    async def create_task(self, ctx: OpContext, body: AddTaskRequest) -> TaskView:
        now = utcnow()
        task = Task(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            title=body.title,
            notes=body.notes,
            status=body.status,
        )
        return TaskView.model_validate(await self._tasks.create_task(ctx, task))

    async def update_task(self, ctx: OpContext, task_id: UUID, body: UpdateTaskRequest) -> TaskView:
        current = await self._tasks.get_task(ctx, task_id)
        changed = current.model_copy(
            update={"title": body.title, "notes": body.notes, "status": body.status}
        )
        return TaskView.model_validate(await self._tasks.update_task(ctx, changed))

    async def delete_task(self, ctx: OpContext, task_id: UUID) -> TaskView:
        return TaskView.model_validate(await self._tasks.delete_task(ctx, task_id))
