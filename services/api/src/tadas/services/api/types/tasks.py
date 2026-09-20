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
    `assignee_id` unassigns the task. `version` is the task's version as the
    caller read it: the update lands only when the task is still at it, and
    is refused with 409 `version_mismatch` when another write landed since,
    so the caller reads again and decides over the current task."""

    title: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    status: TaskStatus | None = None
    assignee_id: UUID | None = None
    version: int = Field(ge=1)


class MoveTaskRequest(RequestBody):
    """Places an open task right after `after_id`; null puts it at the top.
    `version` is the moved task's, as on `UpdateTaskRequest`."""

    after_id: UUID | None = None
    version: int = Field(ge=1)
