"""The tasks service: what the wire can do with tasks, in views."""

from uuid import UUID

from tadas.om.opcontext import OpContext
from tadas.services.api.types.tasks import AddTaskRequest, TaskView, UpdateTaskRequest


class TasksServiceInterface:
    async def get_tasks(self, ctx: OpContext, limit: int) -> list[TaskView]: ...

    async def get_task(self, ctx: OpContext, task_id: UUID) -> TaskView: ...

    async def create_task(self, ctx: OpContext, body: AddTaskRequest) -> TaskView: ...

    async def update_task(
        self, ctx: OpContext, task_id: UUID, body: UpdateTaskRequest
    ) -> TaskView: ...

    async def delete_task(self, ctx: OpContext, task_id: UUID) -> TaskView: ...
