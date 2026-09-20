"""The NOOP handler: the maintenance worker does no work beyond the sweep,
and this handler keeps the loop honest for the kinds that come next."""

import logging

from tadas.om.opcontext import OpContext
from tadas.om.work.types.handler import WorkHandlerInterface
from tadas.om.work.types.work_item import WorkItem

log = logging.getLogger(__name__)


class NoopHandlerImpl(WorkHandlerInterface):
    """Idempotent by construction: handling the same item twice changes nothing.
    It holds nothing per item: it runs for the life of the worker."""

    async def handle(self, ctx: OpContext, item: WorkItem) -> None:
        log.info(
            "noop %s for %s in org %s (attempt %d)",
            item.id,
            item.target_id,
            ctx.org_id,
            item.attempts,
        )
