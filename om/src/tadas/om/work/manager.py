"""The work swimlane: the table-backed queue that durable background work
rides, and the claim that produces the context the work runs under."""

from collections.abc import Sequence
from datetime import timedelta

from tadas.om.opcontext import OpContext
from tadas.om.work.types.work_item import WorkItem, WorkKind


class WorkManagerInterface:
    async def enqueue(self, ctx: OpContext, item: WorkItem) -> WorkItem: ...

    async def claim(
        self, queue: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[OpContext, WorkItem] | None:
        """Platform-internal: claims the oldest available item and rebuilds the
        enqueuer's principal under the service role; returns the context with the item."""
        ...

    async def complete(self, ctx: OpContext, item: WorkItem) -> WorkItem: ...

    async def fail(self, ctx: OpContext, item: WorkItem, error: str) -> WorkItem:
        """Requeues with a growing delay, or fails the item at max_attempts."""
        ...

    async def defer(self, ctx: OpContext, item: WorkItem, delay: timedelta) -> WorkItem:
        """Hands the item back for later without spending an attempt."""
        ...

    async def release(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        """Hands the item back now without spending an attempt."""
        ...

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        """Renews the lease; raises LeaseLost when the item is no longer this worker's."""
        ...

    async def requeue_stale(self) -> int:
        """Platform-internal: returns every item whose lease expired to the queue, everywhere."""
        ...

    async def maintenance_contexts(self) -> list[OpContext]:
        """Platform-internal: one service context per live tenant, for the sweep."""
        ...
