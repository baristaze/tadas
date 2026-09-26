from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update

from tadas.om.exceptions import DuplicateIdempotencyKey, UniqueKeyTaken
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.storage.tables.idempotency_records import IdempotencyRecords
from tadas.om.idempotency.types.record import IdempotencyRecord
from tadas.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from tadas.om.storage.utils.translation import to_model


class IdempotencyStoragePostgresImpl(PgStorageBase, IdempotencyStorageInterface):
    async def write_record(self, org_id: UUID, record: IdempotencyRecord) -> None:
        try:
            await self._upsert(IdempotencyRecords, org_id, record)
        except UniqueKeyTaken as error:
            raise DuplicateIdempotencyKey(f"idempotency key {record.key!r} is taken") from error

    async def read_record(self, org_id: UUID, user_id: UUID, key: str) -> IdempotencyRecord | None:
        stmt = select(IdempotencyRecords).where(
            IdempotencyRecords.org_id == org_id,
            IdempotencyRecords.user_id == user_id,
            IdempotencyRecords.key == key,
        )
        async with self._session_for(stmt, org_id=org_id, user_id=user_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, IdempotencyRecord)

    async def finish_pending(
        self, org_id: UUID, user_id: UUID, key: str, attempt_id: UUID, status: int, body: str
    ) -> IdempotencyRecord | None:
        stmt = (
            update(IdempotencyRecords)
            .where(
                IdempotencyRecords.org_id == org_id,
                IdempotencyRecords.user_id == user_id,
                IdempotencyRecords.key == key,
                IdempotencyRecords.status.is_(None),
                IdempotencyRecords.attempt_id == attempt_id,
            )
            .values(status=status, body=body)
            .returning(IdempotencyRecords)
        )
        async with self._session_for(stmt, org_id=org_id, user_id=user_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            finished = to_model(row, IdempotencyRecord)
            await session.commit()
            return finished

    async def release_pending(
        self, org_id: UUID, user_id: UUID, key: str, attempt_id: UUID
    ) -> bool:
        stmt = (
            update(IdempotencyRecords)
            .where(
                IdempotencyRecords.org_id == org_id,
                IdempotencyRecords.user_id == user_id,
                IdempotencyRecords.key == key,
                IdempotencyRecords.status.is_(None),
                IdempotencyRecords.attempt_id == attempt_id,
            )
            .values(attempt_id=None)
            .returning(IdempotencyRecords.id)
        )
        async with self._session_for(stmt, org_id=org_id, user_id=user_id) as session:
            released = (await session.execute(stmt)).scalar_one_or_none() is not None
            await session.commit()
            return released

    async def purge_records(
        self, org_id: UUID, finished_before: datetime, attempts_before: UUID, limit: int
    ) -> int:
        stmt = delete_batch(
            IdempotencyRecords,
            IdempotencyRecords.org_id == org_id,
            or_(
                and_(
                    or_(
                        IdempotencyRecords.status.is_not(None),
                        IdempotencyRecords.attempt_id.is_(None),
                    ),
                    IdempotencyRecords.created_at < finished_before,
                ),
                and_(
                    IdempotencyRecords.status.is_(None),
                    IdempotencyRecords.attempt_id < attempts_before,
                ),
            ),
            limit=limit,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            purged = deleted(await session.execute(stmt))
            await session.commit()
            return purged

    async def take_over_pending(
        self,
        org_id: UUID,
        user_id: UUID,
        key: str,
        abandoned_before: UUID,
        attempt_id: UUID,
    ) -> IdempotencyRecord | None:
        stmt = (
            update(IdempotencyRecords)
            .where(
                IdempotencyRecords.org_id == org_id,
                IdempotencyRecords.user_id == user_id,
                IdempotencyRecords.key == key,
                IdempotencyRecords.status.is_(None),
                # A token below the bound began before the lease: tokens are
                # uuid_v7 and sort by the millisecond they carry. A released
                # marker holds none, so the comparison passes it by.
                IdempotencyRecords.attempt_id < abandoned_before,
            )
            .values(attempt_id=attempt_id)
            .returning(IdempotencyRecords)
        )
        async with self._session_for(stmt, org_id=org_id, user_id=user_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            taken = to_model(row, IdempotencyRecord)
            await session.commit()
            return taken

    async def rearm_released(
        self, org_id: UUID, user_id: UUID, key: str, attempt_id: UUID
    ) -> IdempotencyRecord | None:
        stmt = (
            update(IdempotencyRecords)
            .where(
                IdempotencyRecords.org_id == org_id,
                IdempotencyRecords.user_id == user_id,
                IdempotencyRecords.key == key,
                IdempotencyRecords.status.is_(None),
                IdempotencyRecords.attempt_id.is_(None),
            )
            .values(attempt_id=attempt_id)
            .returning(IdempotencyRecords)
        )
        async with self._session_for(stmt, org_id=org_id, user_id=user_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            armed = to_model(row, IdempotencyRecord)
            await session.commit()
            return armed
