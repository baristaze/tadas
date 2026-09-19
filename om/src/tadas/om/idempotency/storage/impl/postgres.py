from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from tadas.om.exceptions import DuplicateIdempotencyKey
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.storage.tables.idempotency_records import IdempotencyRecords
from tadas.om.idempotency.types.record import IdempotencyRecord
from tadas.om.storage.impl.pg_base import PgStorageBase
from tadas.om.storage.utils.translation import to_model


class IdempotencyStoragePostgresImpl(PgStorageBase, IdempotencyStorageInterface):
    async def write_record(self, org_id: UUID, record: IdempotencyRecord) -> None:
        try:
            await self._upsert(IdempotencyRecords, org_id, record)
        except IntegrityError as error:
            raise DuplicateIdempotencyKey(f"idempotency key {record.key!r} is taken") from error

    async def read_record(self, org_id: UUID, user_id: UUID, key: str) -> IdempotencyRecord | None:
        stmt = select(IdempotencyRecords).where(
            IdempotencyRecords.org_id == org_id,
            IdempotencyRecords.user_id == user_id,
            IdempotencyRecords.key == key,
        )
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, IdempotencyRecord)

    async def release_pending(self, org_id: UUID, user_id: UUID, key: str) -> None:
        stmt = delete(IdempotencyRecords).where(
            IdempotencyRecords.org_id == org_id,
            IdempotencyRecords.user_id == user_id,
            IdempotencyRecords.key == key,
            IdempotencyRecords.status.is_(None),
        )
        async with self._session_for(stmt) as session:
            await session.execute(stmt)
            await session.commit()

    async def take_over_pending(
        self,
        org_id: UUID,
        user_id: UUID,
        key: str,
        abandoned_before: datetime,
        restarted_at: datetime,
    ) -> IdempotencyRecord | None:
        stmt = (
            update(IdempotencyRecords)
            .where(
                IdempotencyRecords.org_id == org_id,
                IdempotencyRecords.user_id == user_id,
                IdempotencyRecords.key == key,
                IdempotencyRecords.status.is_(None),
                IdempotencyRecords.created_at < abandoned_before,
            )
            .values(created_at=restarted_at)
            .returning(IdempotencyRecords)
        )
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            taken = to_model(row, IdempotencyRecord)
            await session.commit()
            return taken
