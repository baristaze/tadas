from tadas.om.base import Platform
from tadas.om.events.manager import EventsManagerInterface
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event
from tadas.om.opcontext import OpContext, Permission
from tadas.om.tenancy import TenancyManagerInterface


class EventsOptions(Platform):
    max_limit: int = 500
    purge_batch: int = 1000  # events of an expired tenant one purge deletes at most


class EventsManagerImpl(EventsManagerInterface):
    def __init__(
        self,
        storage: EventStorageInterface,
        tenancy: TenancyManagerInterface,
        options: EventsOptions,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._options = options

    async def append_event(self, ctx: OpContext, event: Event) -> Event:
        ctx.require(Permission.WRITE)
        # The tenant and the provenance are the context's, whatever the caller built.
        stamped = event.model_copy(
            update={
                "org_id": ctx.org_id,
                "actor_id": ctx.user_id,
                "request_id": ctx.request_id,
                "app": ctx.app.type.value,
            }
        )
        return await self._storage.append_event(ctx.org_id, stamped)

    async def get_events(self, ctx: OpContext, after_seq: int, limit: int) -> list[Event]:
        ctx.require(Permission.READ)
        return await self._storage.read_after(ctx.org_id, max(0, after_seq), self._clamp(limit))

    async def purge_expired(self, ctx: OpContext) -> int:
        ctx.require(Permission.WRITE)
        if await self._tenancy.tenant_expired(ctx):
            return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)
        return 0

    async def get_head(self, ctx: OpContext) -> int:
        ctx.require(Permission.READ)
        return await self._storage.read_head(ctx.org_id)

    def _clamp(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_limit))
