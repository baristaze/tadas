from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from tadas.om.base import utcnow
from tadas.om.exceptions import DuplicateWorkItem
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable
from tadas.om.work.rules import attempts_after_claim, is_exhausted, stagger_delay
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

    async def write_item_if_held(
        self, org_id: UUID, worker_id: str, item: WorkItem
    ) -> WorkItem | None:
        async with self._lock:
            stored = self._get(self._items, org_id, item.id)
            if (
                stored is None
                or stored.status is not WorkStatus.CLAIMED
                or stored.claimed_by != worker_id
            ):
                return None
            self._items[item.id] = (org_id, item)
            return item

    async def claim_next(
        self, lane: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[UUID, WorkItem] | None:
        now = utcnow()
        async with self._lock:
            for org_id, item in self._rows_across_tenants(self._items):
                if (
                    item.lane == lane
                    and item.status is WorkStatus.QUEUED
                    and item.kind in kinds
                    and item.available_at <= now
                ):
                    claimed = item.model_copy(
                        update={
                            "status": WorkStatus.CLAIMED,
                            "claimed_by": worker_id,
                            "lease_expires_at": now + lease,
                            "attempts": attempts_after_claim(item.attempts),
                            "updated_at": now,
                        }
                    )
                    self._items[item.id] = (org_id, claimed)
                    return org_id, claimed
        return None

    async def requeue_stale(
        self, org_id: UUID, now: datetime, stagger: timedelta, updated_by: UUID
    ) -> list[WorkItem]:
        changed: list[WorkItem] = []
        async with self._lock:
            stale = [
                item
                for item in self._rows(self._items, org_id)
                if item.status is WorkStatus.CLAIMED
                and item.lease_expires_at is not None
                and item.lease_expires_at < now
            ]
            for position, item in enumerate(stale):
                if is_exhausted(item):
                    update = {"status": WorkStatus.FAILED}
                else:
                    update = {
                        "status": WorkStatus.QUEUED,
                        "available_at": now + stagger_delay(position, stagger),
                    }
                requeued = item.model_copy(
                    update={
                        **update,
                        "claimed_by": None,
                        "lease_expires_at": None,
                        "last_error": "lease expired",
                        "updated_at": now,
                        "updated_by": updated_by,
                    }
                )
                self._items[item.id] = (org_id, requeued)
                changed.append(requeued)
        return changed

    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None:
        return self._get(self._items, org_id, item_id)
