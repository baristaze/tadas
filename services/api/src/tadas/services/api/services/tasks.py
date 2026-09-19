"""The tasks service: what the wire can do with tasks, in views."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.opcontext import OpContext
from tadas.om.tasks.types.task import TaskScope, TaskStatus
from tadas.services.api.types.tasks import (
    AddTaskRequest,
    MoveTaskRequest,
    TaskPageView,
    TaskView,
    UpdateTaskRequest,
)


class TasksServiceInterface(ABC):
    @abstractmethod
    async def get_tasks(
        self,
        ctx: OpContext,
        status: TaskStatus,
        scope: TaskScope,
        cursor: str | None,
        limit: int,
    ) -> TaskPageView: ...

    @abstractmethod
    async def get_task(self, ctx: OpContext, task_id: UUID) -> TaskView: ...

    @abstractmethod
    async def create_task(self, ctx: OpContext, body: AddTaskRequest, task_id: UUID) -> TaskView:
        """`task_id` is minted by the gateway before the idempotency marker, so a
        retried create lands on the same id."""
        ...

    @abstractmethod
    async def update_task(
        self, ctx: OpContext, task_id: UUID, body: UpdateTaskRequest
    ) -> TaskView: ...

    @abstractmethod
    async def move_task(self, ctx: OpContext, task_id: UUID, body: MoveTaskRequest) -> TaskView: ...

    @abstractmethod
    async def delete_task(self, ctx: OpContext, task_id: UUID) -> TaskView: ...
