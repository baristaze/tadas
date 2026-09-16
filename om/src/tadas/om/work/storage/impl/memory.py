from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from tadas.om.base import utcnow
from tadas.om.exceptions import DuplicateWorkItem
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus


class WorkStorageMemoryImpl(MemoryStorageBase, WorkStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._items: MemoryTable[WorkItem] = {}

    async def write_item(self, org_id: UUID, item: WorkItem) -> None:
        for _, existing in self._items.values():
            if existing.idempotency_key == item.idempotency_key and existing.id != item.id:
                raise DuplicateWorkItem(f"idempotency key {item.idempotency_key} is taken")
        self._put(self._items, org_id, item)

    async def claim_next(
        self, queue: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[UUID, WorkItem] | None:
        now = utcnow()
        async with self._lock:
            for org_id, item in self._rows_across_tenants(self._items):
                if (
                    item.queue == queue
                    and item.status is WorkStatus.QUEUED
                    and item.kind in kinds
                    and item.available_at <= now
                ):
                    claimed = item.model_copy(
                        update={
                            "status": WorkStatus.CLAIMED,
                            "claimed_by": worker_id,
                            "lease_expires_at": now + lease,
                            "attempts": item.attempts + 1,
                            "updated_at": now,
                        }
                    )
                    self._items[item.id] = (org_id, claimed)
                    return org_id, claimed
        return None

    async def read_stale(self, before: datetime) -> list[tuple[UUID, WorkItem]]:
        return [
            (org_id, item)
            for org_id, item in self._rows_across_tenants(self._items)
            if item.status is WorkStatus.CLAIMED
            and item.lease_expires_at is not None
            and item.lease_expires_at < before
        ]

    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None:
        return self._get(self._items, org_id, item_id)
