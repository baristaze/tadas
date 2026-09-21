from datetime import datetime
from uuid import UUID

from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class EventStorageMemoryImpl(MemoryStorageBase, EventStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._events: MemoryTable[Event] = {}
        # The twin of the cursor row: the last seq assigned, per tenant.
        self._cursors: dict[UUID, int] = {}

    async def append_event(self, org_id: UUID, event: Event) -> Event:
        async with self._lock:
            stored = self._get(self._events, org_id, event.id)
            if stored is not None:
                return stored
            # The tenant and the number are storage's, as the columns are in
            # Postgres: an event that names another tenant is corrected. The
            # write is fenced before the number is spent, the way Postgres
            # rolls the number back with the insert it refused, so an id
            # another tenant owns never moves this tenant's cursor.
            appended = event.model_copy(update={"org_id": org_id})
            self._fence(self._events, org_id, appended)
            seq = self._cursors.get(org_id, 0) + 1
            self._cursors[org_id] = seq
            appended = appended.model_copy(update={"seq": seq})
            self._put(self._events, org_id, appended)
            return appended

    async def read_after(self, org_id: UUID, after_seq: int, limit: int) -> list[Event]:
        newer = [e for e in self._rows(self._events, org_id) if e.seq > after_seq]
        return sorted(newer, key=lambda e: e.seq)[:limit]

    async def purge_tenant(self, org_id: UUID) -> int:
        async with self._lock:
            gone = [e.id for e in self._rows(self._events, org_id)]
            for event_id in gone:
                del self._events[event_id]
            self._cursors.pop(org_id, None)
            return len(gone)

    async def count_since(self, since: datetime) -> int:
        return sum(1 for event in self._every(self._events) if event.produced_at >= since)

    async def read_head(self, org_id: UUID) -> int:
        return self._cursors.get(org_id, 0)
