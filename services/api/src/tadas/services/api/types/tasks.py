from datetime import datetime
from uuid import UUID

from pydantic import Field

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


class TaskPageView(View):
    """One page of a task list. `next_cursor` fetches the next page of the same
    list, open or done, and is null on the last page. The page size is
    clamped, and a list the clamp cut still says a page follows."""

    items: list[TaskView]
    next_cursor: str | None


class AddTaskRequest(RequestBody):
    title: str = Field(max_length=500)
    notes: str = ""
    assignee_id: UUID | None = None


class UpdateTaskRequest(RequestBody):
    """A partial update: absent fields are kept. An explicit null
    `assignee_id` unassigns the task. The version the update compares with is
    the task's as the caller read it, in the `If-Match` header: the update
    lands only when the task is still at it, and is refused with 412
    `precondition_failed` when another write landed since, so the caller reads
    again and decides over the current task. An update that names no version
    is refused with 422 `validation_failed`, since it would overwrite blind."""

    title: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    status: TaskStatus | None = None
    assignee_id: UUID | None = None
    version: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra={"deprecated": True},
        description="Superseded by the `If-Match` header, and accepted in its place "
        "until every client sends the header.",
    )


class MoveTaskRequest(RequestBody):
    """Places an open task right after `after_id`; null puts it at the top.
    `expected_version` is the moved task's as the caller read it: 412
    `precondition_failed` when the task changed since, and 422
    `validation_failed` when the request names no version."""

    after_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)
    version: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra={"deprecated": True},
        description="Superseded by `expected_version`, and accepted in its place "
        "until every client sends it.",
    )
