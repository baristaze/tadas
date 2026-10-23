"""Tasks: the org's tasks, their attachments, and their imports from a CSV
file.

- **Tasks.** Open and done lists a page at a time, one task, create, edit,
  move, delete. A task's due date (`due_on`, `YYYY-MM-DD`, never a time) is
  set on the create and set, moved, or cleared (`null`) on the edit. An
  edit and a delete name the version they read, in `If-Match`
  (`/v1/tasks`, `/v1/tasks/{task_id}`, `/v1/tasks/{task_id}/move`).
- **Many tasks at once.** How many tasks the open or the done list shows in
  a scope; completing or reopening the tasks named, at most a thousand, or
  every task of one list, under an Idempotency-Key. The answer names what
  changed and what was left alone, with the reason; a reopen past the
  plan's active tasks changes up to the bound and carries `plan_limit`
  beside what it did (`/v1/tasks/count`, `/v1/tasks/bulk`).
- **The archive.** The done tasks the daily cleanup archived, a page at a
  time, and restoring one to the done list, naming the version read
  (`/v1/tasks/archived`, `/v1/tasks/{task_id}/restore`).
- **Imports.** Starting the upload of a CSV file to import (the bytes and
  the confirm are the media routes'); starting its import, answered 202
  while the worker reads it a hundred rows a step; the org's newest
  imports; one import; resuming one parked on the plan; cancelling one
  that runs or is parked, which keeps the tasks it made
  (`/v1/tasks/imports/files`, `/v1/tasks/imports`,
  `/v1/tasks/imports/{import_id}`, `.../resume`, `.../cancel`). A caller
  reads an import here, or hears of it on the realtime channel. The import
  routes come before a task's, so `/tasks/imports` is never read as a
  task's id.
- **Attachments.** A task's files a page at a time, starting an upload of
  one, removing one (`/v1/tasks/{task_id}/attachments`,
  `/v1/tasks/{task_id}/attachments/{file_id}`). An attachment's bytes, its
  confirm, and its download are the media routes', by the file's id.
- **The operator plane.** An org's open or done tasks, every task of the
  team, a page at a time, with the cursors the tenant's own list hands
  out, under the org named in the path (`/v1/admin/orgs/{org_id}/tasks`).

Each function is one call into the tasks service; the creating ones, and
the bulk change, run under the idempotency record."""

from uuid import UUID

from fastapi import APIRouter, Response

from tadas.om.tasks.types.task import TaskScope, TaskStatus
from tadas.services.api.gateway.admin import OperatorCtx
from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.gateway.precondition import IfMatch
from tadas.services.api.gateway.resolve import TasksService
from tadas.services.api.types.common import LIMIT_DEFAULT, ErrorResponse
from tadas.services.api.types.media import AddFileRequest, FilePageView, FileView
from tadas.services.api.types.tasks import (
    AddTaskRequest,
    BulkTasksRequest,
    BulkTasksView,
    CancelImportRequest,
    ImportPageView,
    ImportView,
    MoveTaskRequest,
    RestoreTaskRequest,
    StartImportRequest,
    TaskCountView,
    TaskPageView,
    TaskView,
    UpdateTaskRequest,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
operator = APIRouter(prefix="/admin", tags=["tasks"])

IMPORTS_LIMIT_DEFAULT = 10


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


@router.get("/archived", response_model=TaskPageView)
async def list_archived_tasks(
    ctx: Ctx,
    tasks: TasksService,
    scope: TaskScope = TaskScope.TEAM,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> TaskPageView:
    """The done tasks the daily cleanup archived, newest first. An archived
    task leaves the done list; it is still read by its id and restored."""
    return await tasks.get_archived_tasks(ctx, scope, cursor, limit)


@router.get("/count", response_model=TaskCountView)
async def count_tasks(
    ctx: Ctx,
    tasks: TasksService,
    status: TaskStatus = TaskStatus.OPEN,
    scope: TaskScope = TaskScope.TEAM,
) -> TaskCountView:
    """How many tasks one list shows: the number a "Mark all" asks about."""
    return await tasks.count_tasks(ctx, status, scope)


@router.post("/bulk", response_model=BulkTasksView)
async def change_tasks(
    ctx: Ctx, tasks: TasksService, body: BulkTasksRequest, idem: Idem
) -> Response:
    # A write of many rows is recorded like a create: a retry of "Mark all"
    # answers what the first call did, and never reaches tasks that joined
    # the list since.
    return await idem.run(200, lambda _attempt: tasks.change_tasks(ctx, body))


@router.post(
    "/imports/files",
    response_model=FileView,
    status_code=201,
    responses={
        403: {"model": ErrorResponse, "description": "feature_off: `media-uploads` is off"},
    },
)
async def create_import_file(
    ctx: Ctx, tasks: TasksService, body: AddFileRequest, idem: Idem
) -> Response:
    """Starts the multipart upload of a CSV file to import (`text/csv`, a
    `.csv` name, at most 1 MB). Then `POST /v1/media/files/{id}/upload`, the
    parts straight to the store, and `POST /v1/media/files/{id}/confirm`."""
    return await idem.run(
        201, lambda attempt: tasks.create_import_file(ctx, body, attempt.target_id)
    )


@router.post("/imports", response_model=ImportView, status_code=202)
async def start_import(
    ctx: Ctx, tasks: TasksService, body: StartImportRequest, idem: Idem
) -> Response:
    """Accepted: the import runs in the background, a hundred rows a step."""
    return await idem.run(202, lambda attempt: tasks.start_import(ctx, body, attempt.target_id))


@router.get("/imports", response_model=ImportPageView)
async def list_imports(
    ctx: Ctx, tasks: TasksService, limit: int = IMPORTS_LIMIT_DEFAULT
) -> ImportPageView:
    return await tasks.get_imports(ctx, limit)


@router.get("/imports/{import_id}", response_model=ImportView)
async def get_import(ctx: Ctx, tasks: TasksService, import_id: UUID) -> ImportView:
    return await tasks.get_import(ctx, import_id)


@router.post("/imports/{import_id}/resume", response_model=ImportView)
async def resume_import(ctx: Ctx, tasks: TasksService, import_id: UUID) -> ImportView:
    """A parked import runs again from the row it stopped at, and parks again
    at once if the plan still has no room. A running one is answered as it
    is; a finished one is refused (422)."""
    return await tasks.resume_import(ctx, import_id)


@router.post("/imports/{import_id}/cancel", response_model=ImportView)
async def cancel_import(
    ctx: Ctx, tasks: TasksService, import_id: UUID, body: CancelImportRequest | None = None
) -> ImportView:
    """A running or a parked import ends: it settles `cancelled`, the tasks it
    made stay, and no plan that rises and no Resume runs it again. Whoever may
    resume it may cancel it. A cancelled one is answered as it is; one that
    succeeded or failed is refused (422)."""
    return await tasks.cancel_import(ctx, import_id, body)


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


@router.post("/{task_id}/restore", response_model=TaskView)
async def restore_task(
    ctx: Ctx, tasks: TasksService, task_id: UUID, body: RestoreTaskRequest
) -> TaskView:
    return await tasks.restore_task(ctx, task_id, body)


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


@router.post(
    "/{task_id}/attachments",
    response_model=FileView,
    status_code=201,
    responses={
        403: {"model": ErrorResponse, "description": "feature_off: `media-uploads` is off"},
    },
)
async def attach_file(
    ctx: Ctx, tasks: TasksService, task_id: UUID, body: AddFileRequest, idem: Idem
) -> Response:
    """A pending attachment, with the store's multipart upload of it started
    and nothing in the store yet: `POST /v1/media/files/{id}/upload` signs
    the parts, which go straight to the store, and the confirm follows."""
    return await idem.run(
        201, lambda attempt: tasks.attach_file(ctx, task_id, body, attempt.target_id)
    )


@router.delete("/{task_id}/attachments/{file_id}", response_model=FileView)
async def remove_attachment(
    ctx: Ctx, tasks: TasksService, task_id: UUID, file_id: UUID
) -> FileView:
    return await tasks.remove_attachment(ctx, task_id, file_id)


@operator.get("/orgs/{org_id}/tasks", response_model=TaskPageView)
async def operator_list_tasks(
    admin: OperatorCtx,
    tasks: TasksService,
    org_id: UUID,
    status: TaskStatus = TaskStatus.OPEN,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> TaskPageView:
    return await tasks.get_org_tasks(admin, org_id, status, cursor, limit)
