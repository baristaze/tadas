"""Storage of the tasks swimlane. Every operation takes org_id first; deleted
tasks never appear in a list."""

from datetime import datetime
from uuid import UUID

from tadas.om.tasks.types.task import Task


class TasksStorageInterface:
    async def read_open_tasks(self, org_id: UUID, for_user: UUID | None, limit: int) -> list[Task]:
        """Open tasks by position, then id. With `for_user`, only that user's:
        assigned to them, or unassigned and created by them."""
        ...

    async def read_done_tasks(
        self,
        org_id: UUID,
        for_user: UUID | None,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Task]:
        """Done tasks newest first by (updated_at, id), strictly before `before`."""
        ...

    async def read_open_positions(self, org_id: UUID, exclude: UUID | None) -> list[float]:
        """Every open task's position in the org, ascending; the neighbours a
        placement needs, whatever list the caller was looking at."""
        ...

    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None: ...

    async def write_task(self, org_id: UUID, task: Task) -> None: ...
