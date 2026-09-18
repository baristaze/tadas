from datetime import datetime
from uuid import UUID

from tadas.om.base import utcnow
from tadas.om.outbox.storage import OutboxLandingInterface, OutboxStorageInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.memory_base import MemoryTable


class OutboxStorageMemoryImpl(OutboxStorageInterface, OutboxLandingInterface):
    """Holds no base of its own: the memory base of every other namespace lands
    rows here through `OutboxLandingInterface`, which the storage root hands them."""

    def __init__(self) -> None:
        self._rows: MemoryTable[OutboxRow] = {}

    def land(self, org_id: UUID, row: OutboxRow) -> None:
        # The memory twin of "inserted in the same commit as the core row".
        self._rows[row.id] = (org_id, row)

    async def read_pending(self, limit: int) -> list[tuple[UUID, OutboxRow]]:
        pending = [(org, row) for org, row in self._rows.values() if row.done_at is None]
        return sorted(pending, key=lambda pair: pair[1].id)[:limit]

    async def mark_done(self, org_id: UUID, row_id: UUID) -> None:
        found = self._rows.get(row_id)
        if found is None or found[0] != org_id or found[1].done_at is not None:
            return
        self._rows[row_id] = (org_id, found[1].model_copy(update={"done_at": utcnow()}))

    async def purge_done(self, before: datetime) -> int:
        gone = [
            row_id
            for row_id, (_, row) in self._rows.items()
            if row.done_at is not None and row.done_at < before
        ]
        for row_id in gone:
            del self._rows[row_id]
        return len(gone)
