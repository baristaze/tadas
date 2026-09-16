"""Task routes: list, get, create, update, delete. Each function is one call
into the tasks service; the creating one runs under the idempotency record."""

from uuid import UUID

from fastapi import APIRouter, Response

from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.gateway.resolve import TasksService
from tadas.services.api.types.common import LIMIT_DEFAULT
from tadas.services.api.types.tasks import AddTaskRequest, TaskView, UpdateTaskRequest

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskView])
async def list_tasks(ctx: Ctx, tasks: TasksService, limit: int = LIMIT_DEFAULT) -> list[TaskView]:
    return await tasks.get_tasks(ctx, limit)


@router.get("/{task_id}", response_model=TaskView)
async def get_task(ctx: Ctx, tasks: TasksService, task_id: UUID) -> TaskView:
    return await tasks.get_task(ctx, task_id)


@router.post("", response_model=TaskView, status_code=201)
async def create_task(ctx: Ctx, tasks: TasksService, body: AddTaskRequest, idem: Idem) -> Response:
    return await idem.run(201, lambda: tasks.create_task(ctx, body))


@router.put("/{task_id}", response_model=TaskView)
async def update_task(
    ctx: Ctx, tasks: TasksService, task_id: UUID, body: UpdateTaskRequest
) -> TaskView:
    return await tasks.update_task(ctx, task_id, body)


@router.delete("/{task_id}", response_model=TaskView)
async def delete_task(ctx: Ctx, tasks: TasksService, task_id: UUID) -> TaskView:
    return await tasks.delete_task(ctx, task_id)
