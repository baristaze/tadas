"""Storage of the event stream. Append assigns the tenant's next sequence
number from the tenant's cursor row, inside its own transaction; it is the one
named atomic method of this namespace, and the one number storage assigns,
because only the database can order commits."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.events.types.event import Event


class EventStorageInterface(ABC):
    @abstractmethod
    async def append(self, org_id: UUID, event: Event) -> Event:
        """One transaction: takes the tenant's next seq from its cursor row, writes
        the event with it, and returns it. Two concurrent appends queue on the
        cursor and never share a seq or leave a gap behind; an append that rolls
        back returns its number with it. Idempotent on the id: an event already
        appended is returned as stored, and the retry consumes no number."""
        ...

    @abstractmethod
    async def read_after(self, org_id: UUID, after_seq: int, limit: int) -> list[Event]:
        """The tenant's events with seq greater than `after_seq`, ascending."""
        ...

    @abstractmethod
    async def read_head(self, org_id: UUID) -> int:
        """The tenant's last assigned seq, read from the cursor row; 0 before the
        first append. What a client that has seen no push yet replays from, and
        the number every pong carries."""
        ...
