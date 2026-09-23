"""Task routes: the open and done lists, get, create, a partial update, move,
delete, and a task's attachments. Each function is one call into the tasks
service; the creating ones run under the idempotency record. An attachment's
bytes, its confirm, and its download are the media routes', by the file's
id."""

from uuid import UUID

from fastapi import APIRouter, Response

from tadas.om.tasks.types.task import TaskScope, TaskStatus
from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.gateway.precondition import IfMatch
from tadas.services.api.gateway.resolve import TasksService
from tadas.services.api.types.common import LIMIT_DEFAULT
from tadas.services.api.types.media import AddFileRequest, FilePageView, FileView
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


@router.delete("/{task_id}", response_model=TaskView)
async def delete_task(ctx: Ctx, tasks: TasksService, task_id: UUID, if_match: IfMatch) -> TaskView:
    # A DELETE has no body, so the version rides the `If-Match` header, the
    # same precondition the update carries, refused with the same 412.
    return await tasks.delete_task(ctx, task_id, if_match)


@router.get("/{task_id}/attachments", response_model=FilePageView)
async def list_attachments(
    ctx: Ctx,
    tasks: TasksService,
    task_id: UUID,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> FilePageView:
    return await tasks.get_attachments(ctx, task_id, cursor, limit)


@router.post("/{task_id}/attachments", response_model=FileView, status_code=201)
async def attach_file(
    ctx: Ctx, tasks: TasksService, task_id: UUID, body: AddFileRequest, idem: Idem
) -> Response:
    return await idem.run(
        201, lambda attempt: tasks.attach_file(ctx, task_id, body, attempt.target_id)
    )


@router.delete("/{task_id}/attachments/{file_id}", response_model=FileView)
async def remove_attachment(
    ctx: Ctx, tasks: TasksService, task_id: UUID, file_id: UUID
) -> FileView:
    return await tasks.remove_attachment(ctx, task_id, file_id)
