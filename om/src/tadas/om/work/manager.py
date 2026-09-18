"""The work swimlane: the table-backed queue that durable background work
rides, and the claim that produces the context the work runs under."""

from collections.abc import Sequence
from datetime import timedelta

from tadas.om.opcontext import OpContext
from tadas.om.work.types.work_item import WorkItem, WorkKind


class WorkManagerInterface:
    async def enqueue(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        """Raises ValidationFailed when the payload is not the shape WORK_PAYLOADS
        fixes for the kind, DuplicateWorkItem on a reused idempotency key."""
        ...

    async def claim(
        self, lane: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[OpContext, WorkItem] | None:
        """Platform-internal: claims the oldest available item on the lane and rebuilds the
        enqueuer's principal under the service role; returns the context with the item."""
        ...

    async def complete(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        """Every transition of a claimed item (complete, fail, defer, release,
        extend_lease) raises NotFound when the item is gone and LeaseLost when it
        is no longer claimed by `item.claimed_by`; the write is conditional on
        the claim, so a lost lease is never written over."""
        ...

    async def fail(self, ctx: OpContext, item: WorkItem, error: str) -> WorkItem:
        """Requeues with a growing delay, or fails the item at max_attempts. A failed
        item is a dead letter: an audit event names it and a metric counts it."""
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

    async def requeue_stale(self, ctx: OpContext) -> int:
        """The sweep, for one tenant: returns every item whose lease expired to the
        queue, or fails it when its attempts are spent; returns how many it moved."""
        ...

    async def maintenance_contexts(self) -> list[OpContext]:
        """Platform-internal: one service context per live tenant, for the sweep."""
        ...
