from uuid import UUID

from tadas.om.exceptions import DuplicateIdempotencyKey
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.types.record import IdempotencyRecord
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class IdempotencyStorageMemoryImpl(MemoryStorageBase, IdempotencyStorageInterface):
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
        for record in self._rows(self._records, org_id):
            if record.user_id == user_id and record.key == key:
                return record
        return None
