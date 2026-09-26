"""Storage of the event stream. Append assigns the tenant's next sequence
number from the tenant's cursor row, inside its own transaction; it is the one
number storage assigns, because only the database can order commits. The trim
is the other atomic method: it deletes from the bottom of the stream and moves
the tenant's floor in one transaction, so the stream above the floor is whole."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from tadas.om.events.types.event import Event


class EventStorageInterface(ABC):
    @abstractmethod
    async def append_event(self, org_id: UUID, event: Event) -> Event:
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
    async def count_since(self, since: datetime) -> int:
        """Global: how many events were produced at or after `since`, across
        every tenant; the traffic the operator plane's size reads."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID) -> int:
        """The hard delete of a deleted tenant's stream once its retention has
        passed: every event and the cursor row, as every namespace drops a
        tenant past it; returns how many events went. The one delete this
        append-only stream has."""
        ...

    @abstractmethod
    async def trim(self, org_id: UUID, before: datetime, limit: int) -> int:
        """One transaction, under the cursor row's lock: of the tenant's lowest
        `limit` events above the floor, the run from the bottom produced before
        `before` is deleted, and the floor moves to the last seq of that run.
        The run stops at the first younger event, even when older ones follow
        it, because `seq` follows the relay and not the write: the stream above
        the floor stays whole. Returns how many events went; 0 when none was
        old enough, and on a second trim that raced the first."""
        ...

    @abstractmethod
    async def read_floor(self, org_id: UUID) -> int:
        """The tenant's floor, read from the cursor row: the highest seq the
        trim removed, 0 while it removed none. Every event above it, up to
        the head, is stored."""
        ...

    @abstractmethod
    async def read_head(self, org_id: UUID) -> int:
        """The tenant's last assigned seq, read from the cursor row; 0 before the
        first append. What a client that has seen no push yet replays from, and
        the number every pong carries."""
        ...
