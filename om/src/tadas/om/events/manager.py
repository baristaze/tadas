"""The events swimlane: the append-only stream behind every realtime push.
A producer records the event before it publishes; a client replays the
stream from the last sequence it saw."""

from uuid import UUID

from tadas.om.events.types.event import Event
from tadas.om.opcontext import OpContext


class EventsManagerInterface:
    async def record(
        self, ctx: OpContext, entity: str, entity_id: UUID, action: str, idempotency_key: UUID
    ) -> Event:
        """Appends the event to the tenant's stream and returns it with its seq."""
        ...

    async def get_events(self, ctx: OpContext, after_seq: int, limit: int) -> list[Event]:
        """The tenant's events after `after_seq`, oldest first."""
        ...
