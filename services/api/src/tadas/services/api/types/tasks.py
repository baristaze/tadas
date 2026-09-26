from datetime import date, datetime
from uuid import UUID

from pydantic import Field

from tadas.om.orchestrations.types.orchestration import (
    FailReason,
    OrchestrationStatus,
    ParkReason,
)
from tadas.om.tasks.types.task import TaskStatus
from tadas.services.api.types.common import RequestBody, View


class TaskView(View):
    id: UUID
    title: str
    notes: str
    status: TaskStatus
    assignee_id: UUID | None
    position: float
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    deleted_at: datetime | None
    version: int
    # Later fields default, so a client reads a response from a build that
    # predates them.
    due_on: date | None = None
    reminded_at: datetime | None = None
    # Set when the daily cleanup archived the task; null otherwise.
    archived_at: datetime | None = None


class TaskPageView(View):
    """One page of a task list. `next_cursor` fetches the next page of the same
    list, open or done, and is null on the last page. The page size is
    clamped, and a list the clamp cut still says a page follows."""

    items: list[TaskView]
    next_cursor: str | None


class AddTaskRequest(RequestBody):
    """`due_on` is the day the task is due, `YYYY-MM-DD`, never a time. It
    schedules one reminder at nine in the morning of that day, in the time
    zone of the person the task is for (the assignee, or the creator), pushed
    to every open screen of the org and posted to its Slack channel when one
    is connected."""

    title: str = Field(max_length=500)
    notes: str = ""
    assignee_id: UUID | None = None
    due_on: date | None = None


class UpdateTaskRequest(RequestBody):
    """A partial update: absent fields are kept. An explicit null
    `assignee_id` unassigns the task. The version the update compares with is
    the task's as the caller read it, in the `If-Match` header: the update
    lands only when the task is still at it, and is refused with 412
    `precondition_failed` when another write landed since, so the caller reads
    again and decides over the current task. An update that names no version
    is refused with 422 `validation_failed`, since it would overwrite blind.
    An explicit null `due_on` clears the due date; a new one reschedules the
    reminder, and the one scheduled before it never goes out."""

    title: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    status: TaskStatus | None = None
    assignee_id: UUID | None = None
    due_on: date | None = None


class MoveTaskRequest(RequestBody):
    """Places an open task right after `after_id`; null puts it at the top.
    `expected_version` is the moved task's as the caller read it: 412
    `precondition_failed` when the task changed since, and 422
    `validation_failed` when the request names no version."""

    after_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)


class RestoreTaskRequest(RequestBody):
    """Takes an archived task back to the done list. `expected_version` is the
    task's as the caller read it: 412 `precondition_failed` when it changed
    since, and 422 `validation_failed` when the request names none or the
    task is not archived."""

    expected_version: int | None = Field(default=None, ge=1)


class StartImportRequest(RequestBody):
    """The import of a CSV file uploaded under the `task_import` purpose
    (`POST /v1/tasks/imports/files`, then the media routes) and confirmed.
    Its columns are `title` (needed), `notes`, `due_on` (`YYYY-MM-DD`), and
    `assignee_email` (a member of the org), by header name."""

    file_id: UUID


class RowErrorView(View):
    """A row the import skipped: its number, the first data row being 1, and why."""

    row: int
    reason: str


class ImportView(View):
    """An import of tasks from a CSV file, read as it runs. `status` is
    `running`, `parked`, `succeeded`, or `failed`. `total` is the file's data
    rows, null until the first step counted them; `cursor` is how many were
    read; `created` the tasks the import made, `skipped` the rows it passed
    over, and `row_errors` the first twenty of those with the reason. A
    `parked` import names its `park_reason`: `plan_limit` is the plan's bound
    on active tasks, lifted by a higher plan (which resumes it) or by tasks
    finished and `POST /v1/tasks/imports/{id}/resume`. A `failed` one names
    its `fail_reason`: `file_too_large`, `too_many_rows`, `not_csv`,
    `no_title_column`, `file_gone`, or `defect`. Every change is pushed as
    `orchestrations.orchestration.updated` on the realtime channel."""

    id: UUID
    file_id: UUID
    status: OrchestrationStatus
    total: int | None
    cursor: int
    created: int
    skipped: int
    row_errors: list[RowErrorView]
    park_reason: ParkReason | None
    fail_reason: FailReason | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    created_by: UUID


class ImportPageView(View):
    """The org's newest imports, newest first."""

    items: list[ImportView]
