"""Task routes: the open and done lists, get, create, a partial update, move,
and delete. Each function is one call into the tasks service; the creating
one runs under the idempotency record."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from tadas.om.tasks.types.task import TaskScope, TaskStatus
from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.gateway.precondition import IfMatch
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
    ctx: Ctx, tasks: TasksService, task_id: UUID, body: UpdateTaskRequest, if_match: IfMatch
) -> TaskView:
    return await tasks.update_task(ctx, task_id, body, if_match)


@router.post("/{task_id}/move", response_model=TaskView)
async def move_task(
    ctx: Ctx, tasks: TasksService, task_id: UUID, body: MoveTaskRequest
) -> TaskView:
    return await tasks.move_task(ctx, task_id, body)


LegacyVersion = Annotated[
    int | None,
    Query(
        ge=1,
        deprecated=True,
        description="Superseded by the `If-Match` header, and accepted in its place "
        "until every client sends the header.",
    ),
]


@router.delete("/{task_id}", response_model=TaskView)
async def delete_task(
    ctx: Ctx,
    tasks: TasksService,
    task_id: UUID,
    if_match: IfMatch,
    version: LegacyVersion = None,
) -> TaskView:
    # A DELETE has no body, so the version rides the `If-Match` header, the
    # same precondition the update carries, refused with the same 412.
    return await tasks.delete_task(ctx, task_id, if_match, version)
