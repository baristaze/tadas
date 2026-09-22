from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import DateTime, Interval, delete, func, literal, or_, select, update

from tadas.om.base import EMPTY_UUID, utcnow
from tadas.om.outbox.rules import MAX_DOUBLINGS
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.storage.tables.outbox_rows import OutboxRows
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.pg_base import PgStorageBase
from tadas.om.storage.utils.translation import to_model


class OutboxStoragePostgresImpl(PgStorageBase, OutboxStorageInterface):
    async def claim_pending(
        self,
        limit: int,
        now: datetime,
        grace: timedelta,
        backoff_base: timedelta,
        backoff_cap: timedelta,
    ) -> list[OutboxRow]:
        candidates = (
            select(OutboxRows.id)
            .where(
                OutboxRows.done_at.is_(None),
                OutboxRows.failed_at.is_(None),
                or_(OutboxRows.next_attempt_at.is_(None), OutboxRows.next_attempt_at <= now),
                OutboxRows.created_at < now - grace,
            )
            .order_by(OutboxRows.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            # Materialized, so the candidates are chosen and locked once. As
            # a plain IN subquery the planner may take a semi join that
            # rescans it per row, and each rescan skips the rows this update
            # already changed and locks the next ones: a claim past `limit`
            # that leaves the other sweep nothing.
            .cte("candidates")
            .prefix_with("MATERIALIZED")
        )
        # rules.relay_delay, in SQL: the attempt being spent is attempts + 1,
        # so its delay is base * 2^attempts, capped.
        delay = func.least(
            literal(backoff_base, Interval())
            * func.power(2, func.least(OutboxRows.attempts, MAX_DOUBLINGS)),
            literal(backoff_cap, Interval()),
        )
        stmt = (
            update(OutboxRows)
            .where(OutboxRows.id.in_(select(candidates.c.id)))
            .values(
                attempts=OutboxRows.attempts + 1,
                next_attempt_at=literal(now, DateTime(timezone=True)) + delay,
            )
            .returning(OutboxRows)
        )
        async with self._session_for(stmt, EMPTY_UUID) as session:
            rows = (await session.execute(stmt)).scalars().all()
            claimed = sorted((to_model(row, OutboxRow) for row in rows), key=lambda r: r.id)
            await session.commit()
            return claimed

    async def mark_done(self, org_id: UUID, row_id: UUID) -> None:
        stmt = (
            update(OutboxRows)
            .where(
                OutboxRows.id == row_id,
                OutboxRows.org_id == org_id,
                OutboxRows.done_at.is_(None),
            )
            .values(done_at=utcnow())
        )
        async with self._session_for(stmt, org_id) as session:
            await session.execute(stmt)
            await session.commit()

    async def record_failure(
        self, org_id: UUID, row_id: UUID, error: str, failed_at: datetime | None
    ) -> None:
        stmt = (
            update(OutboxRows)
            .where(
                OutboxRows.id == row_id,
                OutboxRows.org_id == org_id,
                OutboxRows.done_at.is_(None),
            )
            .values(last_error=error, failed_at=failed_at)
        )
        async with self._session_for(stmt, org_id) as session:
            await session.execute(stmt)
            await session.commit()

    async def purge_done(self, before: datetime) -> int:
        stmt = (
            delete(OutboxRows)
            .where(or_(OutboxRows.done_at < before, OutboxRows.failed_at < before))
            .returning(OutboxRows.id)
        )
        async with self._session_for(stmt, EMPTY_UUID) as session:
            purged = len((await session.execute(stmt)).scalars().all())
            await session.commit()
            return purged
