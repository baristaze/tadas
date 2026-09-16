"""The tasks swimlane: the to-do items a team creates, works, and closes."""

from uuid import UUID

from tadas.om.opcontext import OpContext
from tadas.om.tasks.types.task import Task


class TasksManagerInterface:
    async def get_tasks(self, ctx: OpContext, limit: int) -> list[Task]: ...

    async def get_task(self, ctx: OpContext, task_id: UUID) -> Task: ...

    async def create_task(self, ctx: OpContext, task: Task) -> Task: ...

    async def update_task(self, ctx: OpContext, task: Task) -> Task: ...

    async def delete_task(self, ctx: OpContext, task_id: UUID) -> Task: ...
