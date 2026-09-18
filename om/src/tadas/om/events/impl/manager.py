from uuid import UUID

from tadas.om.base import Platform, new_id, utcnow
from tadas.om.events.manager import EventsManagerInterface
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event
from tadas.om.opcontext import OpContext, Permission


class EventsOptions(Platform):
    max_limit: int = 500


class EventsManagerImpl(EventsManagerInterface):
    def __init__(self, storage: EventStorageInterface, options: EventsOptions) -> None:
        self._storage = storage
        self._options = options

    async def record(
        self, ctx: OpContext, entity: str, entity_id: UUID, action: str, idempotency_key: UUID
    ) -> Event:
        # A manager records an event after it authorized its own write; the
        # stream row is that write's consequence, so any member of the tenant
        # who was allowed to write is allowed to record it.
        ctx.require(Permission.READ)
        event = Event(
            id=new_id(),
            entity=entity,
            entity_id=entity_id,
            action=action,
            produced_at=utcnow(),
            idempotency_key=idempotency_key,
            actor_id=ctx.user_id,
            request_id=ctx.request_id,
        )
        return await self._storage.append(ctx.org_id, event)

    async def get_events(self, ctx: OpContext, after_seq: int, limit: int) -> list[Event]:
        ctx.require(Permission.READ)
        return await self._storage.read_after(ctx.org_id, max(0, after_seq), self._clamp(limit))

    def _clamp(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_limit))
