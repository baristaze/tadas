"""Storage of the event stream. Append assigns the tenant's next sequence
number atomically; it is the one named atomic method of this namespace."""

from uuid import UUID

from tadas.om.events.types.event import Event


class EventStorageInterface:
    async def append(self, org_id: UUID, event: Event) -> Event:
        """One statement: writes the event with the tenant's next seq and returns it.
        Two concurrent appends never share a seq and never leave a gap behind."""
        ...

    async def read_after(self, org_id: UUID, after_seq: int, limit: int) -> list[Event]:
        """The tenant's events with seq greater than `after_seq`, ascending."""
        ...
