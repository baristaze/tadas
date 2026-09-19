from uuid import UUID

from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class EventStorageMemoryImpl(MemoryStorageBase, EventStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._events: MemoryTable[Event] = {}
        self._next_seq: dict[UUID, int] = {}

    async def append(self, org_id: UUID, event: Event) -> Event:
        async with self._lock:
            stored = self._get(self._events, org_id, event.id)
            if stored is not None:
                return stored
            seq = self._next_seq.get(org_id, 0) + 1
            self._next_seq[org_id] = seq
            appended = event.model_copy(update={"seq": seq})
            self._put(self._events, org_id, appended)
            return appended

    async def read_after(self, org_id: UUID, after_seq: int, limit: int) -> list[Event]:
        newer = [e for e in self._rows(self._events, org_id) if e.seq > after_seq]
        return sorted(newer, key=lambda e: e.seq)[:limit]

    async def read_head(self, org_id: UUID) -> int:
        return self._next_seq.get(org_id, 0)
