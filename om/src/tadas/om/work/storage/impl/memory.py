from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from tadas.om.base import EMPTY_UUID, new_id, utcnow
from tadas.om.exceptions import TenantMismatch
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable
from tadas.om.work.rules import attempts_after_claim, is_exhausted, stagger_delay
from tadas.om.work.storage import InsertOutcome, WorkStorageInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus


class WorkStorageMemoryImpl(MemoryStorageBase, WorkStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._items: MemoryTable[WorkItem] = {}

    async def create_item(self, org_id: UUID, item: WorkItem) -> InsertOutcome:
        async with self._lock:
            found = self._items.get(item.id)
            if found is not None:
                if found[0] != org_id:
                    raise TenantMismatch(f"work item {item.id} is not in {org_id}")
                return InsertOutcome.ID_EXISTS
            for existing in self._rows(self._items, org_id):
                if existing.idempotency_key == item.idempotency_key:
                    return InsertOutcome.KEY_EXISTS  # the key is taken in this tenant
            self._insert(self._items, org_id, item)
            return InsertOutcome.INSERTED

    async def write_item_if_held(
        self, org_id: UUID, claim_token: UUID, item: WorkItem
    ) -> WorkItem | None:
        async with self._lock:
            stored = self._get(self._items, org_id, item.id)
            if (
                stored is None
                or stored.status is not WorkStatus.CLAIMED
                or stored.claim_token != claim_token
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
                            "claim_token": new_id(),
                            "lease_expires_at": now + lease,
                            "attempts": attempts_after_claim(item.attempts),
                            "updated_at": now,
                            "updated_by": EMPTY_UUID,  # the claim is the platform's write
                        }
                    )
                    self._items[item.id] = (org_id, claimed)
                    return org_id, claimed
        return None

    async def requeue_stale(
        self, org_id: UUID, now: datetime, stagger: timedelta, limit: int
    ) -> list[WorkItem]:
        changed: list[WorkItem] = []
        async with self._lock:
            stale = [
                item
                for item in self._rows(self._items, org_id)
                if item.status is WorkStatus.CLAIMED
                and item.lease_expires_at is not None
                and item.lease_expires_at < now
            ][:limit]
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
                        "claim_token": None,
                        "lease_expires_at": None,
                        "last_error": "lease expired",
                        "updated_at": now,
                        "updated_by": EMPTY_UUID,
                    }
                )
                self._items[item.id] = (org_id, requeued)
                changed.append(requeued)
        return changed

    async def purge_items(self, before: datetime, limit: int) -> int:
        async with self._lock:
            gone = [
                item.id
                for _, item in self._rows_across_tenants(self._items)
                if item.status in (WorkStatus.DONE, WorkStatus.FAILED) and item.updated_at < before
            ][:limit]
            for item_id in gone:
                del self._items[item_id]
            return len(gone)

    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None:
        return self._get(self._items, org_id, item_id)

    async def read_item_by_key(self, org_id: UUID, idempotency_key: UUID) -> WorkItem | None:
        return next(
            (
                item
                for item in self._rows(self._items, org_id)
                if item.idempotency_key == idempotency_key
            ),
            None,
        )
