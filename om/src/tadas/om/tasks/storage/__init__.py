"""Storage of the tasks swimlane. Every operation takes org_id first."""

from uuid import UUID

from tadas.om.tasks.types.task import Task


class TasksStorageInterface:
    async def read_tasks(self, org_id: UUID, limit: int) -> list[Task]: ...

    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None: ...

    async def write_task(self, org_id: UUID, task: Task) -> None: ...
