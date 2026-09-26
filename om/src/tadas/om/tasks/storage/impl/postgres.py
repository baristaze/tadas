from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Double,
    Uuid,
    and_,
    delete,
    func,
    literal,
    or_,
    select,
    true,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert

from tadas.om.base import EMPTY_UUID
from tadas.om.exceptions import PreconditionFailed, TenantMismatch
from tadas.om.orchestrations.storage.impl.postgres import land_step
from tadas.om.orchestrations.types.orchestration import Step
from tadas.om.outbox.storage.tables.outbox_rows import OutboxRows
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.pg_base import PgStorageBase
from tadas.om.storage.utils.translation import to_model, to_row, to_values
from tadas.om.tasks.rules import Place
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.tables.tasks import Tasks
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus


def _live(org_id: UUID, status: TaskStatus) -> ColumnElement[bool]:
    return and_(Tasks.org_id == org_id, Tasks.status == status.value, Tasks.deleted_at.is_(None))


def _archivable(org_id: UUID, before: datetime) -> ColumnElement[bool]:
    """Mirrors tasks.rules.is_archivable in SQL."""
    return and_(
        _live(org_id, TaskStatus.DONE), Tasks.archived_at.is_(None), Tasks.updated_at < before
    )


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


def _after(cursor: OpenTaskCursor) -> ColumnElement[bool]:
    """Mirrors tasks.rules.is_after in SQL."""
    return tuple_(Tasks.position, Tasks.id) > tuple_(
        literal(cursor.position, Double()), literal(cursor.id, Uuid())
    )


def _follows(anchor: Place) -> ColumnElement[bool]:
    """Mirrors tasks.rules.follows in SQL: the pair compared, as the open list
    orders it."""
    return tuple_(Tasks.position, Tasks.id) > tuple_(
        literal(anchor[0], Double()), literal(anchor[1], Uuid())
    )


class TasksStoragePostgresImpl(PgStorageBase, TasksStorageInterface):
    async def read_open_tasks(
        self, org_id: UUID, criterion: TaskFilter, after: OpenTaskCursor | None, limit: int
    ) -> list[Task]:
        stmt = select(Tasks).where(_live(org_id, TaskStatus.OPEN), _visible(criterion))
        if after is not None:
            stmt = stmt.where(_after(after))
        stmt = stmt.order_by(Tasks.position, Tasks.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            result = await session.execute(stmt)
            return [to_model(row, Task) for row in result.scalars()]

    async def read_recent_open_tasks(
        self, org_id: UUID, criterion: TaskFilter, limit: int
    ) -> list[Task]:
        stmt = (
            select(Tasks)
            .where(_live(org_id, TaskStatus.OPEN), _visible(criterion))
            .order_by(Tasks.id.desc())
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            result = await session.execute(stmt)
            return [to_model(row, Task) for row in result.scalars()]

    async def count_open_tasks(self, org_id: UUID, criterion: TaskFilter) -> int:
        stmt = (
            select(func.count())
            .select_from(Tasks)
            .where(_live(org_id, TaskStatus.OPEN), _visible(criterion))
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            return (await session.execute(stmt)).scalar_one()

    async def read_done_tasks(
        self, org_id: UUID, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> list[Task]:
        return await self._done(org_id, criterion, before, limit, archived=False)

    async def read_archived_tasks(
        self, org_id: UUID, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> list[Task]:
        return await self._done(org_id, criterion, before, limit, archived=True)

    async def _done(
        self,
        org_id: UUID,
        criterion: TaskFilter,
        before: TaskCursor | None,
        limit: int,
        *,
        archived: bool,
    ) -> list[Task]:
        shelf = Tasks.archived_at.is_not(None) if archived else Tasks.archived_at.is_(None)
        stmt = select(Tasks).where(_live(org_id, TaskStatus.DONE), shelf, _visible(criterion))
        if before is not None:
            stmt = stmt.where(_before(before))
        stmt = stmt.order_by(Tasks.updated_at.desc(), Tasks.id.desc()).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            result = await session.execute(stmt)
            return [to_model(row, Task) for row in result.scalars()]

    async def read_last_place(self, org_id: UUID) -> Place | None:
        stmt = (
            select(Tasks.position, Tasks.id)
            .where(_live(org_id, TaskStatus.OPEN))
            .order_by(Tasks.position.desc(), Tasks.id.desc())
            .limit(1)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            found = (await session.execute(stmt)).one_or_none()
            return None if found is None else (found.position, found.id)

    async def read_archivable(self, org_id: UUID, before: datetime, limit: int) -> list[UUID]:
        stmt = (
            select(Tasks.id)
            .where(_archivable(org_id, before))
            .order_by(Tasks.updated_at, Tasks.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            return list((await session.execute(stmt)).scalars())

    async def create_tasks_in_step(
        self,
        org_id: UUID,
        tasks: Sequence[tuple[Task, tuple[OutboxRow, ...]]],
        step: Step,
        step_rows: tuple[OutboxRow, ...],
    ) -> tuple[bool, ...]:
        # One transaction: the tasks whose id is not written yet, the rows
        # that announce them, the record's compare-and-set, and its rows. A
        # record another holder moved rolls all of it back.
        async with self._session_for(Tasks, org_id=org_id) as session:
            written: set[UUID] = set()
            if tasks:
                stmt = (
                    insert(Tasks)
                    .values([{"org_id": org_id, **to_values(task, Tasks)} for task, _ in tasks])
                    .on_conflict_do_nothing(index_elements=["id"])
                    .returning(Tasks.id)
                )
                written = set((await session.execute(stmt)).scalars())
            for task, outbox_rows in tasks:
                if task.id in written:
                    for outbox_row in outbox_rows:
                        session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await land_step(session, org_id, step, len(written))
            for outbox_row in step_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return tuple(task.id in written for task, _ in tasks)

    async def update_archived_in_step(
        self,
        org_id: UUID,
        candidates: Sequence[tuple[UUID, tuple[OutboxRow, ...]]],
        before: datetime,
        archived_at: datetime,
        actor: UUID,
        step: Step,
        step_rows: tuple[OutboxRow, ...],
    ) -> tuple[bool, ...]:
        # The condition is the statement's: a candidate reopened, edited, or
        # deleted since it was read no longer matches it and is left alone.
        async with self._session_for(Tasks, org_id=org_id) as session:
            archived: set[UUID] = set()
            if candidates:
                stmt = (
                    update(Tasks)
                    .where(
                        Tasks.id.in_([task_id for task_id, _ in candidates]),
                        _archivable(org_id, before),
                    )
                    .values(
                        archived_at=archived_at,
                        updated_at=archived_at,
                        updated_by=actor,
                        version=Tasks.version + 1,
                    )
                    .returning(Tasks.id)
                )
                archived = set((await session.execute(stmt)).scalars())
            for task_id, outbox_rows in candidates:
                if task_id in archived:
                    for outbox_row in outbox_rows:
                        session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await land_step(session, org_id, step, len(archived))
            for outbox_row in step_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return tuple(task_id in archived for task_id, _ in candidates)

    async def read_open_places(
        self, org_id: UUID, exclude: UUID | None, after: Place | None, limit: int
    ) -> list[Place]:
        # Ordered by (position, id), the order the open list reads: positions
        # tie, and the id decides between two that do (tasks.rules.Place).
        stmt = select(Tasks.position, Tasks.id).where(_live(org_id, TaskStatus.OPEN))
        if exclude is not None:
            stmt = stmt.where(Tasks.id != exclude)
        if after is not None:
            stmt = stmt.where(_follows(after))
        stmt = stmt.order_by(Tasks.position, Tasks.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            return [(position, task_id) for position, task_id in (await session.execute(stmt))]

    async def read_task(self, org_id: UUID, task_id: UUID) -> Task | None:
        stmt = select(Tasks).where(Tasks.org_id == org_id, Tasks.id == task_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Task)

    async def count_created_since(self, since: datetime) -> int:
        stmt = select(func.count()).select_from(Tasks).where(Tasks.created_at >= since)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return (await session.execute(stmt)).scalar_one()

    async def purge_deleted(self, org_id: UUID, before: datetime) -> int:
        stmt = (
            delete(Tasks)
            .where(Tasks.org_id == org_id, Tasks.deleted_at < before)
            .returning(Tasks.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            purged = len((await session.execute(stmt)).scalars().all())
            await session.commit()
            return purged

    async def purge_tenant(self, org_id: UUID) -> int:
        stmt = delete(Tasks).where(Tasks.org_id == org_id).returning(Tasks.id)
        async with self._session_for(stmt, org_id=org_id) as session:
            purged = len((await session.execute(stmt)).scalars().all())
            await session.commit()
            return purged

    async def create_task(
        self, org_id: UUID, task: Task, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(Tasks, org_id, task, outbox_rows)

    async def update_task(
        self, org_id: UUID, task: Task, expected_version: int, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        await self.update_tasks(org_id, [(task, expected_version, outbox_rows)])

    async def update_tasks(
        self, org_id: UUID, updates: Sequence[tuple[Task, int, tuple[OutboxRow, ...]]]
    ) -> None:
        # The compare-and-set is the statement itself: the version is in the
        # WHERE, so two writers from one snapshot cannot both land. The outbox
        # rows join the commit only when every update hit a row; one that
        # missed rolls the transaction back with nothing landed.
        async with self._session_for(Tasks, org_id=org_id) as session:
            for task, expected_version, _ in updates:
                values = {k: v for k, v in to_values(task, Tasks).items() if k != "id"}
                stmt = (
                    update(Tasks)
                    .where(
                        Tasks.id == task.id,
                        Tasks.org_id == org_id,
                        Tasks.version == expected_version,
                    )
                    .values(**values)
                    .returning(Tasks.id)
                )
                if (await session.execute(stmt)).scalar_one_or_none() is None:
                    await session.rollback()
                    raise await self._why_not(org_id, task.id, expected_version)
            for _, _, outbox_rows in updates:
                for outbox_row in outbox_rows:
                    session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()

    async def _why_not(
        self, org_id: UUID, task_id: UUID, expected_version: int
    ) -> TenantMismatch | PreconditionFailed:
        """Which of the three conditions the compare-and-set missed: the row is
        gone, it is another tenant's, or it has moved. The row is read after
        the failed statement, so the version it names is a report, never a
        value to retry with.

        The question is cross-tenant by nature. It asks where a row this
        tenant could not write is, and a transaction narrowed to this tenant
        cannot tell "another tenant holds it" from "nobody does": the policy
        answers both with no row. So the read takes the system scope, spelled
        here, in a session of its own, since the rollback above already ended
        the transaction the settings lived in. It reads two columns of one id
        and reports which condition missed, which is what it reported before
        the policy existed."""
        stmt = select(Tasks.org_id, Tasks.version).where(Tasks.id == task_id)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            found = (await session.execute(stmt)).one_or_none()
        if found is None:
            return PreconditionFailed(f"task {task_id} is gone")
        if found.org_id != org_id:
            return TenantMismatch(f"tasks {task_id} is not in {org_id}")
        return PreconditionFailed(
            f"task {task_id} is at version {found.version}, not {expected_version}"
        )

    async def mark_reminded(
        self,
        org_id: UUID,
        task_id: UUID,
        due_on: date,
        reminded_at: datetime,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> Task | None:
        stmt = (
            update(Tasks)
            .where(
                Tasks.id == task_id,
                Tasks.org_id == org_id,
                Tasks.status == TaskStatus.OPEN.value,
                Tasks.deleted_at.is_(None),
                Tasks.due_on == due_on,
                Tasks.reminded_at.is_(None),
            )
            .values(reminded_at=reminded_at, version=Tasks.version + 1)
            .returning(Tasks)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                await session.rollback()
                return None
            written = to_model(row, Task)
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return written
