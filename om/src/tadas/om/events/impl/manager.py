from datetime import timedelta

from pydantic import Field

from tadas.om.base import Platform, utcnow
from tadas.om.events.manager import EventsManagerInterface
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event
from tadas.om.exceptions import StreamTruncated
from tadas.om.opcontext import OpContext, Permission
from tadas.om.tenancy import TenancyManagerInterface


class EventsOptions(Platform):
    max_limit: int = 500
    retention: timedelta | None = None
    """How long a living tenant's events are kept. None keeps every one, and
    the sweep never moves the floor (ADR 0040)."""
    purge_batch: int = Field(default=1000, gt=0)
    """The most events one purge call deletes from one tenant's stream, by
    the trim or under a tenant past its retention; the sweep calls again
    while a batch comes back full."""


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
        after = max(0, after_seq)
        page = await self._storage.read_after(ctx.org_id, after, self._clamp(limit))
        # The floor is read after the page. A trim that committed before the
        # page was read is seen here too, so a page with a hole never leaves.
        floor = await self._storage.read_floor(ctx.org_id)
        if after < floor:
            raise StreamTruncated(floor=floor, head=await self._storage.read_head(ctx.org_id))
        return page

    async def purge_expired(self, ctx: OpContext) -> int:
        ctx.require(Permission.WRITE)
        if await self._tenancy.tenant_expired(ctx):
            return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)
        if self._options.retention is None:
            return 0
        before = utcnow() - self._options.retention
        return await self._storage.trim(ctx.org_id, before, self._options.purge_batch)

    async def get_head(self, ctx: OpContext) -> int:
        ctx.require(Permission.READ)
        return await self._storage.read_head(ctx.org_id)

    def _clamp(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_limit))
