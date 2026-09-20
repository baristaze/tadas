"""The events swimlane: the append-only stream behind every realtime push.
The outbox relay appends one event per entity write through the event
storage; an audit producer (the work manager's dead letter) appends through
this manager under its context, which stamps the provenance. A client
replays the stream from the last sequence it saw. Append-only: no update,
no delete."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from uuid import UUID

from tadas.om.base import utcnow
from tadas.om.events.types.event import Event
from tadas.om.opcontext import OpContext, ProvenanceScope


class EventsManagerInterface(ABC):
    @abstractmethod
    async def append(self, ctx: OpContext, event: Event) -> Event:
        """Appends an audit event under the caller's tenant. An append is a
        write, so WRITE is required, and the provenance the row records (the
        actor, the request, the app) is stamped from the context, never taken
        from the caller's event. The entity events behind every push are not
        appended here: the outbox relay writes them through the event storage.
        Idempotent on `event.id`: an id already appended returns the stored
        event."""
        ...

    @abstractmethod
    async def get_events(self, ctx: OpContext, after_seq: int, limit: int) -> list[Event]:
        """The tenant's events after `after_seq`, oldest first."""
        ...

    @abstractmethod
    async def get_head(self, ctx: OpContext) -> int:
        """The tenant's stream position: the last seq assigned, 0 before the
        first event. A client that opens the channel starts here."""
        ...


def audit_event(
    ctx: ProvenanceScope, event_id: UUID, kind: str, target_id: UUID, facts: Mapping[str, object]
) -> Event:
    """An audit entry: the event shape plus the actor, the request, and the app,
    which is all it reads from the context."""
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
