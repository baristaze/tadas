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


class TaskPageView(View):
    """One page of a task list. `next_cursor` fetches the next page of the done
    list; it is null on the last page and always for the open list."""

    items: list[TaskView]
    next_cursor: str | None


class AddTaskRequest(RequestBody):
    title: str = Field(max_length=500)
    notes: str = ""
    assignee_id: UUID | None = None


class UpdateTaskRequest(RequestBody):
    """A partial update: absent fields are kept. An explicit null
    `assignee_id` unassigns the task."""

    title: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    status: TaskStatus | None = None
    assignee_id: UUID | None = None


class MoveTaskRequest(RequestBody):
    """Places an open task right after `after_id`; null puts it at the top."""

    after_id: UUID | None = None
