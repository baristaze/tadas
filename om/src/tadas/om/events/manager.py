"""The events swimlane: the append-only stream behind every realtime push.
The outbox relay appends one event per entity write through the event
storage; an audit producer appends through this manager under its context.
A client replays the stream from the last sequence it saw. Append-only: no
update, no delete."""

from collections.abc import Mapping
from uuid import UUID

from tadas.om.base import utcnow
from tadas.om.events.types.event import Event
from tadas.om.opcontext import OpContext


class EventsManagerInterface:
    async def append(self, ctx: OpContext, event: Event) -> Event:
        """Appends an audit event under the caller's tenant; the write it records
        was authorized by the manager that made it, so READ is enough. Idempotent
        on `event.id`: an id already appended returns the stored event."""
        ...

    async def get_events(self, ctx: OpContext, after_seq: int, limit: int) -> list[Event]:
        """The tenant's events after `after_seq`, oldest first."""
        ...


def audit_event(
    ctx: OpContext, event_id: UUID, kind: str, target_id: UUID, facts: Mapping[str, object]
) -> Event:
    """An audit entry: the event shape plus the principal and the app, from the context."""
    return Event(
        id=event_id,
        kind=kind,
        target_id=target_id,
        payload=facts,
        produced_at=utcnow(),
        actor_id=ctx.user_id,
        request_id=ctx.request_id,
        app=ctx.app.type.value,
    )
