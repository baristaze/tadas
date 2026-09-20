from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import DateTime, Interval, case, delete, func, literal, select, update

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import DuplicateWorkItem, TenantMismatch, UniqueKeyTaken
from tadas.om.storage.impl.pg_base import PgStorageBase
from tadas.om.storage.utils.translation import to_model, to_values
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.storage.tables.work_items import WorkItems
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus


class WorkStoragePostgresImpl(PgStorageBase, WorkStorageInterface):
    async def create_item(self, org_id: UUID, item: WorkItem) -> bool:
        # The base reports a taken id as False (a retry) and names any other
        # unique key it hit; the one here is the idempotency key, a conflict.
        try:
            if await self._insert(WorkItems, org_id, item):
                return True
        except UniqueKeyTaken as error:
            raise DuplicateWorkItem(f"idempotency key {item.idempotency_key} is taken") from error
        async with self._session_for(WorkItems) as session:
            row = await session.get(WorkItems, item.id)
        if row is None:
            raise DuplicateWorkItem(f"idempotency key {item.idempotency_key} is taken")
        if row.org_id != org_id:
            raise TenantMismatch(f"work item {item.id} is not in {org_id}")
        return False

    async def write_item_if_held(
        self, org_id: UUID, claim_token: UUID, item: WorkItem
    ) -> WorkItem | None:
        values = to_values(item, WorkItems)
        values.pop("id", None)
        stmt = (
            update(WorkItems)
            .where(
                WorkItems.id == item.id,
                WorkItems.org_id == org_id,
                WorkItems.status == WorkStatus.CLAIMED.value,
                WorkItems.claim_token == claim_token,
            )
            .values(**values)
            .returning(WorkItems)
        )
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            written = to_model(row, WorkItem)
            await session.commit()
            return written

    async def claim_next(
        self, lane: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[UUID, WorkItem] | None:
        now = utcnow()
        candidate = (
            select(WorkItems.id)
            .where(
                WorkItems.lane == lane,
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
                claim_token=new_id(),
                lease_expires_at=now + lease,
                attempts=WorkItems.attempts + 1,  # rules.attempts_after_claim, in SQL
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

    async def requeue_stale(
        self, org_id: UUID, now: datetime, stagger: timedelta, updated_by: UUID
    ) -> list[WorkItem]:
        stale_filter = (
            WorkItems.org_id == org_id,
            WorkItems.status == WorkStatus.CLAIMED.value,
            WorkItems.lease_expires_at < now,
        )
        stale = (
            select(
                WorkItems.id.label("id"),
                (func.row_number().over(order_by=WorkItems.id) - 1).label("position"),
            )
            .where(*stale_filter)
            .subquery("stale")
        )
        exhausted = WorkItems.attempts >= WorkItems.max_attempts  # rules.is_exhausted, in SQL
        staggered = (
            literal(now, DateTime(timezone=True)) + literal(stagger, Interval()) * stale.c.position
        )
        stmt = (
            update(WorkItems)
            .where(WorkItems.id == stale.c.id, *stale_filter)
            .values(
                status=case((exhausted, WorkStatus.FAILED.value), else_=WorkStatus.QUEUED.value),
                available_at=case((exhausted, WorkItems.available_at), else_=staggered),
                claimed_by=None,
                claim_token=None,
                lease_expires_at=None,
                last_error="lease expired",
                updated_at=now,
                updated_by=updated_by,
            )
            .returning(WorkItems)
        )
        async with self._session_for(stmt) as session:
            rows = (await session.execute(stmt)).scalars().all()
            changed = sorted((to_model(row, WorkItem) for row in rows), key=lambda item: item.id)
            await session.commit()
            return changed

    async def purge_settled(self, org_id: UUID, before: datetime) -> int:
        stmt = (
            delete(WorkItems)
            .where(
                WorkItems.org_id == org_id,
                WorkItems.status.in_([WorkStatus.DONE.value, WorkStatus.FAILED.value]),
                WorkItems.updated_at < before,
            )
            .returning(WorkItems.id)
        )
        async with self._session_for(stmt) as session:
            purged = len((await session.execute(stmt)).scalars().all())
            await session.commit()
            return purged

    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None:
        stmt = select(WorkItems).where(WorkItems.org_id == org_id, WorkItems.id == item_id)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, WorkItem)
