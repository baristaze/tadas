from datetime import datetime
from uuid import UUID

from tadas.services.api.types.common import RequestBody, View


class TaskView(View):
    id: UUID
    title: str
    notes: str
    status: str
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    deleted_at: datetime | None


class AddTaskRequest(RequestBody):
    title: str
    notes: str = ""
    status: str = "open"


class UpdateTaskRequest(RequestBody):
    title: str
    notes: str
    status: str
