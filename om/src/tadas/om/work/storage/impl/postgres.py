from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from tadas.om.base import utcnow
from tadas.om.exceptions import DuplicateWorkItem
from tadas.om.storage.impl.pg_base import PgStorageBase
from tadas.om.storage.utils.translation import to_model
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.storage.tables.work_items import WorkItems
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus


class WorkStoragePostgresImpl(PgStorageBase, WorkStorageInterface):
    async def write_item(self, org_id: UUID, item: WorkItem) -> None:
        try:
            await self._upsert(WorkItems, org_id, item)
        except IntegrityError as error:
            raise DuplicateWorkItem(f"idempotency key {item.idempotency_key} is taken") from error

    async def claim_next(
        self, queue: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[UUID, WorkItem] | None:
        now = utcnow()
        candidate = (
            select(WorkItems.id)
            .where(
                WorkItems.queue == queue,
                WorkItems.status == WorkStatus.QUEUED.value,
                WorkItems.kind.in_([kind.value for kind in kinds]),
                WorkItems.available_at <= now,
            )
            .order_by(WorkItems.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            update(WorkItems)
            .where(WorkItems.id == candidate)
            .values(
                status=WorkStatus.CLAIMED.value,
                claimed_by=worker_id,
                lease_expires_at=now + lease,
                attempts=WorkItems.attempts + 1,
                updated_at=now,
            )
            .returning(WorkItems)
        )
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            claimed = (row.org_id, to_model(row, WorkItem))
            await session.commit()
            return claimed

    async def read_stale(self, before: datetime) -> list[tuple[UUID, WorkItem]]:
        stmt = (
            select(WorkItems)
            .where(
                WorkItems.status == WorkStatus.CLAIMED.value,
                WorkItems.lease_expires_at < before,
            )
            .order_by(WorkItems.id)
        )
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [(row.org_id, to_model(row, WorkItem)) for row in result.scalars()]

    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None:
        stmt = select(WorkItems).where(WorkItems.org_id == org_id, WorkItems.id == item_id)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, WorkItem)
