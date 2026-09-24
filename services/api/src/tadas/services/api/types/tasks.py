from datetime import date, datetime
from uuid import UUID

from pydantic import AwareDatetime, Field

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
    # Replaced by `due_on`, and always null: a client of the release before
    # reads it as "no due time". The release after this one removes it.
    remind_at: datetime | None = Field(default=None, deprecated=True)


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
    is connected. `remind_at`, the due time of the release before, is still
    taken for one release: its date, in its own offset, is the due date, and
    `due_on` wins when both are sent."""

    title: str = Field(max_length=500)
    notes: str = ""
    assignee_id: UUID | None = None
    due_on: date | None = None
    remind_at: AwareDatetime | None = Field(default=None, deprecated=True)


class UpdateTaskRequest(RequestBody):
    """A partial update: absent fields are kept. An explicit null
    `assignee_id` unassigns the task. The version the update compares with is
    the task's as the caller read it, in the `If-Match` header: the update
    lands only when the task is still at it, and is refused with 412
    `precondition_failed` when another write landed since, so the caller reads
    again and decides over the current task. An update that names no version
    is refused with 422 `validation_failed`, since it would overwrite blind.
    An explicit null `due_on` clears the due date; a new one reschedules the
    reminder, and the one scheduled before it never goes out. `remind_at`
    is taken for one release, as on the add."""

    title: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    status: TaskStatus | None = None
    assignee_id: UUID | None = None
    due_on: date | None = None
    remind_at: AwareDatetime | None = Field(default=None, deprecated=True)


class MoveTaskRequest(RequestBody):
    """Places an open task right after `after_id`; null puts it at the top.
    `expected_version` is the moved task's as the caller read it: 412
    `precondition_failed` when the task changed since, and 422
    `validation_failed` when the request names no version."""

    after_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)
