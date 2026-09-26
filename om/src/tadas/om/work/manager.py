"""The work swimlane: the table-backed queue that durable background work
rides, and the claim that produces the context the work runs under."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from tadas.om.opcontext import OpContext, RequestContext
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.work.types.work_item import WorkItem, WorkKind


class WorkManagerInterface(ABC):
    @abstractmethod
    async def enqueue(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        """A create: the copy stamps the actor, the timestamps, status QUEUED, and
        zero attempts, and clears every claim field, whatever the caller sent.
        The request that caused the work and its trace context are the item's,
        constructed by the caller from its own context, and the copy leaves
        them alone. An id already written returns the row as stored, so a
        retried enqueue never resets a claim, and so does a reused idempotency
        key: the insert reports which key collided and the manager reads the
        row back by it. Raises ValidationFailed when the payload is not the
        shape WORK_PAYLOADS fixes for the kind."""
        ...

    @abstractmethod
    async def enqueue_relayed(self, org_id: UUID, row: OutboxRow) -> WorkItem:
        """Platform-internal: the enqueue of a work item that follows a core write,
        which the relay makes from the row of kind `work.<kind>` that rode that
        write. It takes no context, because the relay runs without a principal,
        and stamps the actor from the row, along with the request that made the
        write and that request's trace context, which the run names as its
        cause and links its spans to. The row's id is the item's
        `idempotency_key`, the same on every run of the relay, so a relay that
        runs twice and a caller that retries meet one row under one key. Raises
        ValidationFailed when the row names a kind this build does not know or
        carries a payload outside the shape WORK_PAYLOADS fixes for it."""
        ...

    @abstractmethod
    async def claim(
        self,
        rctx: RequestContext,
        lane: str,
        kinds: Sequence[WorkKind],
        worker_id: str,
        lease: timedelta,
    ) -> tuple[OpContext, WorkItem] | None:
        """Platform-internal: claims the oldest available item on the lane and rebuilds the
        enqueuer's principal under the service role, refining the request stage the
        worker minted for this claim; returns the context with the item. The
        stage it returns names the item's `request_id` as its
        `caused_by_request_id`, so the run names both the request it is and the
        request that caused it. An item
        whose tenant is gone cannot be run and cannot be retried into existence:
        it is failed in the same call, with the reason, and the claim moves on
        to the next item, so no row stays claimed with nobody to settle it."""
        ...

    @abstractmethod
    async def complete(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        """Every transition of a claimed item (complete, fail, defer, release,
        extend_lease) raises NotFound when the item is gone and LeaseLost when it
        is no longer claimed by `item.claimed_by`; the write is conditional on
        the claim, so a lost lease is never written over."""
        ...

    @abstractmethod
    async def fail(self, ctx: OpContext, item: WorkItem, error: str) -> WorkItem:
        """Requeues with a growing delay, or fails the item at max_attempts. A failed
        item is a dead letter: an audit event names it and a metric counts it."""
        ...

    @abstractmethod
    async def defer(self, ctx: OpContext, item: WorkItem, delay: timedelta) -> WorkItem:
        """Hands the item back for later without spending an attempt."""
        ...

    @abstractmethod
    async def release(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        """Hands the item back now without spending an attempt."""
        ...

    @abstractmethod
    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        """Renews the lease; raises LeaseLost when the item is no longer this worker's."""
        ...

    @abstractmethod
    async def requeue_stale(self, ctx: OpContext, limit: int) -> int:
        """The sweep, for one tenant: returns up to `limit` items whose lease
        expired to the queue, or fails them when their attempts are spent;
        returns how many it moved. `limit` is the sweep's batch size; what is
        left over waits for the next sweep."""
        ...

    @abstractmethod
    async def purge_items(self) -> int:
        """Platform-internal: the sweep, across tenants, like the outbox's
        purge: deletes items done or failed past the retention, a batch at a
        time; returns how many. The one hard delete of the namespace. It takes no context,
        because it runs for no tenant and no principal."""
        ...

    @abstractmethod
    async def maintenance_contexts(self, rctx: RequestContext) -> list[OpContext]:
        """Platform-internal: the tenancy manager's service contexts (the system
        scope first, then every tenant), for the sweep, each refining the request
        stage the worker minted for this pass."""
        ...

    @abstractmethod
    async def mark_purged(self, ctx: OpContext) -> bool:
        """Platform-internal: the tenancy manager's `mark_purged`, for the sweep,
        once a pass found nothing left of the tenant to trim."""
        ...
