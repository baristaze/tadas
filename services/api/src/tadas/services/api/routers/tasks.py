"""Task routes: list, get, create, update, delete. Each function builds the
entity or the arguments from the request, calls one manager operation, and
projects the result onto a view."""

from uuid import UUID

from fastapi import APIRouter, Request, Response

from tadas.om.base import new_id, utcnow
from tadas.om.tasks.types.task import Task
from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.types.common import LIMIT_DEFAULT, clamp_limit
from tadas.services.api.types.tasks import AddTaskRequest, TaskView, UpdateTaskRequest

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _tasks(request: Request):
    return request.app.state.container.managers.tasks


@router.get("", response_model=list[TaskView])
async def list_tasks(request: Request, ctx: Ctx, limit: int = LIMIT_DEFAULT) -> list[TaskView]:
    tasks = await _tasks(request).get_tasks(ctx, clamp_limit(limit))
    return [TaskView.model_validate(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskView)
async def get_task(request: Request, ctx: Ctx, task_id: UUID) -> TaskView:
    return TaskView.model_validate(await _tasks(request).get_task(ctx, task_id))


@router.post("", response_model=TaskView, status_code=201)
async def create_task(request: Request, ctx: Ctx, body: AddTaskRequest, idem: Idem) -> Response:
    if (replay := await idem.replay()) is not None:
        return replay
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
    created = await _tasks(request).create_task(ctx, task)
    return await idem.store(TaskView.model_validate(created), 201)


@router.put("/{task_id}", response_model=TaskView)
async def update_task(
    request: Request, ctx: Ctx, task_id: UUID, body: UpdateTaskRequest
) -> TaskView:
    current = await _tasks(request).get_task(ctx, task_id)
    changed = current.model_copy(
        update={"title": body.title, "notes": body.notes, "status": body.status}
    )
    return TaskView.model_validate(await _tasks(request).update_task(ctx, changed))


@router.delete("/{task_id}", response_model=TaskView)
async def delete_task(request: Request, ctx: Ctx, task_id: UUID) -> TaskView:
    return TaskView.model_validate(await _tasks(request).delete_task(ctx, task_id))
