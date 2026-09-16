from uuid import UUID

from sqlalchemy import select

from tadas.om.storage.impl.pg_base import PgStorageBase
from tadas.om.storage.utils.translation import to_model
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.tables.tasks import Tasks
from tadas.om.tasks.types.task import Task


class TasksStoragePostgresImpl(PgStorageBase, TasksStorageInterface):
    async def read_tasks(self, org_id: UUID, limit: int) -> list[Task]:
        stmt = (
            select(Tasks)
            .where(Tasks.org_id == org_id, Tasks.deleted_at.is_(None))
            .order_by(Tasks.id)
            .limit(limit)
        )
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [to_model(row, Task) for row in result.scalars()]

    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None:
        stmt = select(Tasks).where(Tasks.org_id == org_id, Tasks.id == task_id)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Task)

    async def write_task(self, org_id: UUID, task: Task) -> None:
        await self._upsert(Tasks, org_id, task)
