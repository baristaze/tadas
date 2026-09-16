import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from tadas.infra.topics import Topics, TopicsInterface, WorkAvailablePayload
from tadas.om.base import Platform, new_id, utcnow
from tadas.om.exceptions import LeaseLost, NotFound
from tadas.om.opcontext import AppContext, AppType, OpContext, Permission
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.work.manager import WorkManagerInterface
from tadas.om.work.rules import attempts_after_hand_back, is_exhausted, retry_delay
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

log = logging.getLogger(__name__)


class WorkOptions(Platform):
    base_retry_delay: timedelta = timedelta(seconds=30)
    max_retry_delay: timedelta = timedelta(minutes=15)
    stale_stagger: timedelta = timedelta(seconds=5)


class WorkManagerImpl(WorkManagerInterface):
    def __init__(
        self,
        storage: WorkStorageInterface,
        tenancy: TenancyManagerInterface,
        topics: TopicsInterface,
        options: WorkOptions,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._topics = topics
        self._options = options

    async def enqueue(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        ctx.require(Permission.WRITE)
        await self._storage.write_item(ctx.org_id, item)
        await self._topics.publish(
            Topics.WORK_AVAILABLE,
            WorkAvailablePayload(
                idempotency_key=item.idempotency_key,
                produced_at=utcnow(),
                org_id=ctx.org_id,
                queue=item.queue,
                kind=item.kind.value,
            ),
        )
        return item

    async def claim(
        self, queue: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[OpContext, WorkItem] | None:
        found = await self._storage.claim_next(queue, kinds, worker_id, lease)
        if found is None:
            return None
        org_id, item = found
        ctx = await self._tenancy.service_context(
            org_id,
            item.created_by,
            AppContext(type=AppType.WORKER, version=f"worker@{worker_id}"),
            new_id(),
        )
        return ctx, item

    async def complete(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        return await self._transition(
            ctx,
            item,
            {
                "status": WorkStatus.DONE,
                "claimed_by": None,
                "lease_expires_at": None,
                "updated_at": utcnow(),
            },
        )

    async def fail(self, ctx: OpContext, item: WorkItem, error: str) -> WorkItem:
        now = utcnow()
        if is_exhausted(item):
            update: dict[str, Any] = {"status": WorkStatus.FAILED}
        else:
            delay = retry_delay(
                item.attempts, self._options.base_retry_delay, self._options.max_retry_delay
            )
            update = {"status": WorkStatus.QUEUED, "available_at": now + delay}
        return await self._transition(
            ctx,
            item,
            {
                **update,
                "claimed_by": None,
                "lease_expires_at": None,
                "last_error": error,
                "updated_at": now,
            },
        )

    async def defer(self, ctx: OpContext, item: WorkItem, delay: timedelta) -> WorkItem:
        return await self._hand_back(ctx, item, delay)

    async def release(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        return await self._hand_back(ctx, item, timedelta(0))

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        now = utcnow()
        return await self._transition(
            ctx, item, {"lease_expires_at": now + lease, "updated_at": now}
        )

    async def requeue_stale(self, ctx: OpContext) -> int:
        ctx.require(Permission.WRITE)
        requeued = await self._storage.requeue_stale(
            ctx.org_id, utcnow(), self._options.stale_stagger
        )
        if requeued:
            log.info("requeued %d stale work items in org %s", len(requeued), ctx.org_id)
        return len(requeued)

    async def maintenance_contexts(self) -> list[OpContext]:
        return await self._tenancy.service_contexts(
            AppContext(type=AppType.WORKER, version="worker@maintenance"), new_id()
        )

    async def _hand_back(self, ctx: OpContext, item: WorkItem, delay: timedelta) -> WorkItem:
        now = utcnow()
        return await self._transition(
            ctx,
            item,
            {
                "status": WorkStatus.QUEUED,
                "available_at": now + delay,
                "claimed_by": None,
                "lease_expires_at": None,
                "attempts": attempts_after_hand_back(item.attempts),
                "updated_at": now,
            },
        )

    async def _transition(self, ctx: OpContext, item: WorkItem, update: dict[str, Any]) -> WorkItem:
        """Confirms the item exists, is in this tenant, and is still claimed by the
        worker named on it, then writes the transition conditionally on that claim."""
        ctx.require(Permission.WRITE)
        stored = await self._storage.read_item(ctx.org_id, item.id)
        if stored is None:
            raise NotFound(f"work item {item.id} not found")
        if (
            item.claimed_by is None
            or stored.status is not WorkStatus.CLAIMED
            or stored.claimed_by != item.claimed_by
        ):
            raise LeaseLost(f"work item {item.id} is no longer held by {item.claimed_by}")
        written = await self._storage.write_item_if_held(
            ctx.org_id, item.claimed_by, item.model_copy(update=update)
        )
        if written is None:
            raise LeaseLost(f"work item {item.id} was taken from {item.claimed_by} mid-write")
        return written
