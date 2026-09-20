from tadas.om.base import Platform
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

    async def append(self, ctx: OpContext, event: Event) -> Event:
        ctx.require(Permission.WRITE)
        # The provenance is the context's, whatever the caller built.
        stamped = event.model_copy(
            update={
                "actor_id": ctx.user_id,
                "request_id": ctx.request_id,
                "app": ctx.app.type.value,
            }
        )
        return await self._storage.append(ctx.org_id, stamped)

    async def get_events(self, ctx: OpContext, after_seq: int, limit: int) -> list[Event]:
        ctx.require(Permission.READ)
        return await self._storage.read_after(ctx.org_id, max(0, after_seq), self._clamp(limit))

    async def get_head(self, ctx: OpContext) -> int:
        ctx.require(Permission.READ)
        return await self._storage.read_head(ctx.org_id)

    def _clamp(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_limit))
