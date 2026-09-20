"""Task routes: the open and done lists, get, create, a partial update, move,
and delete. Each function is one call into the tasks service; the creating
one runs under the idempotency record."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from tadas.om.tasks.types.task import TaskScope, TaskStatus
from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.gateway.resolve import TasksService
from tadas.services.api.types.common import LIMIT_DEFAULT
from tadas.services.api.types.tasks import (
    AddTaskRequest,
    MoveTaskRequest,
    TaskPageView,
    TaskView,
    UpdateTaskRequest,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskPageView)
async def list_tasks(
    ctx: Ctx,
    tasks: TasksService,
    status: TaskStatus = TaskStatus.OPEN,
    scope: TaskScope = TaskScope.TEAM,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> TaskPageView:
    return await tasks.get_tasks(ctx, status, scope, cursor, limit)


@router.get("/{task_id}", response_model=TaskView)
async def get_task(ctx: Ctx, tasks: TasksService, task_id: UUID) -> TaskView:
    return await tasks.get_task(ctx, task_id)


@router.post("", response_model=TaskView, status_code=201)
async def create_task(ctx: Ctx, tasks: TasksService, body: AddTaskRequest, idem: Idem) -> Response:
    return await idem.run(201, lambda attempt: tasks.create_task(ctx, body, attempt.target_id))


@router.patch("/{task_id}", response_model=TaskView)
async def update_task(
    ctx: Ctx, tasks: TasksService, task_id: UUID, body: UpdateTaskRequest
) -> TaskView:
    return await tasks.update_task(ctx, task_id, body)


@router.post("/{task_id}/move", response_model=TaskView)
async def move_task(
    ctx: Ctx, tasks: TasksService, task_id: UUID, body: MoveTaskRequest
) -> TaskView:
    return await tasks.move_task(ctx, task_id, body)


Version = Annotated[
    int,
    Query(
        ge=1,
        description="The task's version as the caller read it; 409 `version_mismatch` "
        "when the task changed since.",
    ),
]


@router.delete("/{task_id}", response_model=TaskView)
async def delete_task(ctx: Ctx, tasks: TasksService, task_id: UUID, version: Version) -> TaskView:
    # A DELETE has no body, so the version rides the query string: the same
    # precondition the other writes carry in theirs, typed as a required
    # parameter by every generated client, and refused with the same 409.
    return await tasks.delete_task(ctx, task_id, version)
