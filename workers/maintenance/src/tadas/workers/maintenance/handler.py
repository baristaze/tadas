"""The handlers of NOOP, the kind that keeps the loop honest, and of
SYNC_SEATS, which holds a per-seat subscription's quantity to the org's
active members.

Each handler names the permissions its calls take (`REQUIRES`), and the
tests hold every role that may ask for the kind (the permission on its spec,
`tadas.om.work.kinds`) to them: nobody reaches through the queue what they
could not do directly."""

import logging
from typing import ClassVar

from tadas.om.billing import BillingManagerInterface
from tadas.om.context import Permission, TenantContext
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.work.types.handler import WorkHandlerInterface
from tadas.om.work.types.work_item import WorkItem
from tadas.workers.maintenance.providers import ProviderCalls

log = logging.getLogger(__name__)


class NoopHandlerImpl(WorkHandlerInterface):
    """Idempotent by construction: handling the same item twice changes nothing.
    It holds nothing per item: it runs for the life of the worker."""

    REQUIRES: ClassVar[tuple[Permission, ...]] = ()

    async def handle(self, ctx: TenantContext, item: WorkItem) -> None:
        log.info(
            "noop %s for %s in org %s (attempt %d)",
            item.id,
            item.target_id,
            ctx.org_id,
            item.attempts,
        )


class SyncSeatsHandlerImpl(WorkHandlerInterface):
    """Reads the org's active members when it runs, never when it was asked
    for, and holds the subscription to that count. Items that run late, twice,
    or out of order converge on the members the org has then. The processor
    call carries a key made of the item's claim and the count: the client's
    own retries within one run share it, and a run the queue retries asks
    again, since the processor answers a key it has seen with its first
    answer, a failure included. A run whose change already landed reads the
    count there and asks nothing. A processor out of reach, marked out, or
    refusing the process's own key, parks the item; one that refuses the
    request fails it at once."""

    REQUIRES: ClassVar[tuple[Permission, ...]] = (Permission.READ, Permission.MANAGE_MEMBERS)
    """`count_members` reads; `sync_seats` manages members."""

    def __init__(
        self,
        tenancy: TenancyManagerInterface,
        billing: BillingManagerInterface,
        payments_calls: ProviderCalls,
    ) -> None:
        self._tenancy = tenancy
        self._billing = billing
        self._payments_calls = payments_calls

    async def handle(self, ctx: TenantContext, item: WorkItem) -> None:
        seats = await self._tenancy.members.count_members(ctx)
        async with self._payments_calls.calls():
            await self._billing.sync_seats(ctx, seats, seats_key(item, seats))


def seats_key(item: WorkItem, seats: int) -> str:
    """The key of one claim's change: each claim of the item mints its own
    token, so each run of it is a request of its own."""
    return f"tadas-seats-{item.id}-{item.claim_token}-{seats}"
