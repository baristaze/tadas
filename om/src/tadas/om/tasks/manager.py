"""The tasks swimlane: the to-do items a team creates, works, and closes."""

from uuid import UUID

from tadas.om.opcontext import OpContext
from tadas.om.tasks.types.filter import TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task


class TasksManagerInterface:
    async def get_open_tasks(self, ctx: OpContext, criterion: TaskFilter, limit: int) -> list[Task]:
        """Open tasks the filter shows, in manual order, top first. The filter's
        user is the caller: `mine` is about nobody else."""
        ...

    async def get_done_tasks(
        self, ctx: OpContext, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> list[Task]:
        """Done tasks the filter shows, newest first, strictly before the cursor."""
        ...

    async def get_task(self, ctx: OpContext, task_id: UUID) -> Task: ...

    async def create_task(self, ctx: OpContext, task: Task) -> Task:
        """A new task is open and goes to the top of the open list."""
        ...

    async def update_task(self, ctx: OpContext, task: Task) -> Task:
        """A task reopened from done goes back to the top of the open list."""
        ...

    async def move_task(self, ctx: OpContext, task_id: UUID, after_id: UUID | None) -> Task:
        """Places an open task right after `after_id` in the open list, or at
        the top when it is None."""
        ...

    async def delete_task(self, ctx: OpContext, task_id: UUID) -> Task: ...
