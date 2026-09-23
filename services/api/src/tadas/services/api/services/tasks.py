"""The tasks service: what the wire can do with tasks, in views."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.opcontext import OpContext
from tadas.om.tasks.types.task import TaskScope, TaskStatus
from tadas.services.api.types.media import AddFileRequest, FilePageView, FileView
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
        self, ctx: OpContext, task_id: UUID, body: UpdateTaskRequest, if_match: int | None
    ) -> TaskView:
        """`if_match` is the version the `If-Match` header names, the task's
        as the caller read it. No header is `ValidationFailed`."""
        ...

    @abstractmethod
    async def move_task(self, ctx: OpContext, task_id: UUID, body: MoveTaskRequest) -> TaskView: ...

    @abstractmethod
    async def delete_task(self, ctx: OpContext, task_id: UUID, if_match: int | None) -> TaskView:
        """The version as on the update: the `If-Match` header."""
        ...

    @abstractmethod
    async def attach_file(
        self, ctx: OpContext, task_id: UUID, body: AddFileRequest, file_id: UUID
    ) -> FileView:
        """`file_id` is minted by the gateway before the idempotency marker, as
        a task's id is on the create."""
        ...

    @abstractmethod
    async def get_attachments(
        self, ctx: OpContext, task_id: UUID, cursor: str | None, limit: int
    ) -> FilePageView: ...

    @abstractmethod
    async def remove_attachment(self, ctx: OpContext, task_id: UUID, file_id: UUID) -> FileView: ...
