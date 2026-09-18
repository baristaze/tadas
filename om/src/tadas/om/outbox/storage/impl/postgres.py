from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update

from tadas.om.base import utcnow
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.storage.tables.outbox_rows import OutboxRows
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.pg_base import PgStorageBase
from tadas.om.storage.utils.translation import to_model


class OutboxStoragePostgresImpl(PgStorageBase, OutboxStorageInterface):
    async def read_pending(self, limit: int) -> list[tuple[UUID, OutboxRow]]:
        stmt = (
            select(OutboxRows)
            .where(OutboxRows.done_at.is_(None))
            .order_by(OutboxRows.id)
            .limit(limit)
        )
        async with self._session_for(stmt) as session:
            rows = (await session.execute(stmt)).scalars()
            return [(row.org_id, to_model(row, OutboxRow)) for row in rows]

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
        async with self._session_for(stmt) as session:
            await session.execute(stmt)
            await session.commit()

    async def purge_done(self, before: datetime) -> int:
        stmt = delete(OutboxRows).where(OutboxRows.done_at < before).returning(OutboxRows.id)
        async with self._session_for(stmt) as session:
            purged = len((await session.execute(stmt)).scalars().all())
            await session.commit()
            return purged
