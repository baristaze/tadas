from uuid import UUID

from sqlalchemy import ColumnElement, DateTime, Uuid, and_, literal, or_, select, true, tuple_

from tadas.om.storage.impl.pg_base import PgStorageBase
from tadas.om.storage.utils.translation import to_model
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.tables.tasks import Tasks
from tadas.om.tasks.types.filter import TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus


def _live(org_id: UUID, status: TaskStatus) -> ColumnElement[bool]:
    return and_(Tasks.org_id == org_id, Tasks.status == status.value, Tasks.deleted_at.is_(None))


def _visible(criterion: TaskFilter) -> ColumnElement[bool]:
    """Mirrors tasks.rules.is_visible in SQL."""
    if criterion.scope is TaskScope.TEAM:
        return true()
    return or_(
        Tasks.assignee_id == criterion.user_id,
        and_(Tasks.assignee_id.is_(None), Tasks.created_by == criterion.user_id),
    )


def _before(cursor: TaskCursor) -> ColumnElement[bool]:
    """Mirrors tasks.rules.is_before in SQL."""
    return tuple_(Tasks.updated_at, Tasks.id) < tuple_(
        literal(cursor.updated_at, DateTime(timezone=True)), literal(cursor.id, Uuid())
    )


class TasksStoragePostgresImpl(PgStorageBase, TasksStorageInterface):
    async def read_open_tasks(self, org_id: UUID, criterion: TaskFilter, limit: int) -> list[Task]:
        stmt = (
            select(Tasks)
            .where(_live(org_id, TaskStatus.OPEN), _visible(criterion))
            .order_by(Tasks.position, Tasks.id)
            .limit(limit)
        )
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [to_model(row, Task) for row in result.scalars()]

    async def read_done_tasks(
        self, org_id: UUID, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> list[Task]:
        stmt = select(Tasks).where(_live(org_id, TaskStatus.DONE), _visible(criterion))
        if before is not None:
            stmt = stmt.where(_before(before))
        stmt = stmt.order_by(Tasks.updated_at.desc(), Tasks.id.desc()).limit(limit)
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [to_model(row, Task) for row in result.scalars()]

    async def read_open_positions(self, org_id: UUID, exclude: UUID | None) -> list[float]:
        stmt = select(Tasks.position).where(_live(org_id, TaskStatus.OPEN))
        if exclude is not None:
            stmt = stmt.where(Tasks.id != exclude)
        stmt = stmt.order_by(Tasks.position)
        async with self._session_for(stmt) as session:
            return list((await session.execute(stmt)).scalars())

    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None:
        stmt = select(Tasks).where(Tasks.org_id == org_id, Tasks.id == task_id)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Task)

    async def write_task(self, org_id: UUID, task: Task) -> None:
        await self._upsert(Tasks, org_id, task)
