"""Storage of the event stream. Append assigns the tenant's next sequence
number atomically; it is the one named atomic method of this namespace, and
the one number storage assigns, because only the database can order commits."""

from uuid import UUID

from tadas.om.events.types.event import Event


class EventStorageInterface:
    async def append(self, org_id: UUID, event: Event) -> Event:
        """One statement: writes the event with the tenant's next seq and returns it.
        Two concurrent appends never share a seq and never leave a gap behind.
        Idempotent on the id: an event already appended is returned as stored."""
        ...

    async def read_after(self, org_id: UUID, after_seq: int, limit: int) -> list[Event]:
        """The tenant's events with seq greater than `after_seq`, ascending."""
        ...

    async def read_head(self, org_id: UUID) -> int:
        """The tenant's last assigned seq; 0 before the first append. What a
        client that has seen no push yet replays from."""
        ...
