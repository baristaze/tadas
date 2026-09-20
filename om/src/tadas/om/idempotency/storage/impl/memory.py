from datetime import datetime
from uuid import UUID

from tadas.om.exceptions import DuplicateIdempotencyKey
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.types.record import IdempotencyRecord
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class IdempotencyStorageMemoryImpl(MemoryStorageBase, IdempotencyStorageInterface):
    """Every conditional write reads and writes under the one lock with no
    await in between, so two callers racing for a record never both match."""

    def __init__(self) -> None:
        super().__init__()
        self._records: MemoryTable[IdempotencyRecord] = {}

    async def write_record(self, org_id: UUID, record: IdempotencyRecord) -> None:
        async with self._lock:
            for row_org, existing in self._records.values():
                if (
                    existing.id != record.id
                    and row_org == org_id
                    and existing.user_id == record.user_id
                    and existing.key == record.key
                ):
                    raise DuplicateIdempotencyKey(f"idempotency key {record.key!r} is taken")
            self._put(self._records, org_id, record)

    async def read_record(self, org_id: UUID, user_id: UUID, key: str) -> IdempotencyRecord | None:
        return self._find(org_id, user_id, key)

    async def finish_pending(
        self, org_id: UUID, user_id: UUID, key: str, attempt_id: UUID, status: int, body: str
    ) -> IdempotencyRecord | None:
        async with self._lock:
            stored = self._find(org_id, user_id, key)
            if stored is None or not stored.pending or stored.attempt_id != attempt_id:
                return None
            finished = stored.model_copy(update={"status": status, "body": body})
            self._put(self._records, org_id, finished)
            return finished

    async def release_pending(
        self, org_id: UUID, user_id: UUID, key: str, attempt_id: UUID
    ) -> bool:
        async with self._lock:
            stored = self._find(org_id, user_id, key)
            if stored is None or not stored.pending or stored.attempt_id != attempt_id:
                return False
            del self._records[stored.id]
            return True

    async def take_over_pending(
        self,
        org_id: UUID,
        user_id: UUID,
        key: str,
        abandoned_before: datetime,
        restarted_at: datetime,
        attempt_id: UUID,
    ) -> IdempotencyRecord | None:
        async with self._lock:
            stored = self._find(org_id, user_id, key)
            if stored is None or not stored.pending or stored.created_at >= abandoned_before:
                return None
            taken = stored.model_copy(update={"created_at": restarted_at, "attempt_id": attempt_id})
            self._put(self._records, org_id, taken)
            return taken

    def _find(self, org_id: UUID, user_id: UUID, key: str) -> IdempotencyRecord | None:
        for record in self._rows(self._records, org_id):
            if record.user_id == user_id and record.key == key:
                return record
        return None
