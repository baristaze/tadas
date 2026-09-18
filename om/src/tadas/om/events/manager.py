"""The events swimlane: the append-only stream behind every realtime push.
The outbox relay appends one event per entity write; a client replays the
stream from the last sequence it saw. Append-only: no update, no delete."""

from uuid import UUID

from tadas.om.events.types.event import Event
from tadas.om.opcontext import OpContext


class EventsManagerInterface:
    async def append(self, org_id: UUID, event: Event) -> Event:
        """Platform-internal: the outbox relay, and an audit producer, append an
        event under the tenant it names; the write it records was authorized by
        the manager that made it. Idempotent on `event.id`: an id already
        appended returns the stored event with its seq."""
        ...

    async def get_events(self, ctx: OpContext, after_seq: int, limit: int) -> list[Event]:
        """The tenant's events after `after_seq`, oldest first."""
        ...
