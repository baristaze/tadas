import logging
from collections.abc import Sequence
from datetime import timedelta

from tadas.infra.topics import Topics, TopicsInterface, WorkAvailablePayload
from tadas.om.base import Platform, new_id, utcnow
from tadas.om.exceptions import LeaseLost
from tadas.om.opcontext import AppContext, AppType, OpContext, Permission
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.work.manager import WorkManagerInterface
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

log = logging.getLogger(__name__)


class WorkOptions(Platform):
    base_retry_delay: timedelta = timedelta(seconds=30)
    max_retry_delay: timedelta = timedelta(minutes=15)
    stale_stagger: timedelta = timedelta(seconds=5)


def retry_delay(attempts: int, options: WorkOptions) -> timedelta:
    """A growing delay: base * 2^(attempts-1), capped."""
    grown = options.base_retry_delay * (2 ** max(0, attempts - 1))
    return min(grown, options.max_retry_delay)


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
        ctx.require(Permission.WRITE)
        done = item.model_copy(
            update={
                "status": WorkStatus.DONE,
                "claimed_by": None,
                "lease_expires_at": None,
                "updated_at": utcnow(),
            }
        )
        await self._storage.write_item(ctx.org_id, done)
        return done

    async def fail(self, ctx: OpContext, item: WorkItem, error: str) -> WorkItem:
        ctx.require(Permission.WRITE)
        now = utcnow()
        if item.attempts >= item.max_attempts:
            failed = item.model_copy(
                update={
                    "status": WorkStatus.FAILED,
                    "claimed_by": None,
                    "lease_expires_at": None,
                    "last_error": error,
                    "updated_at": now,
                }
            )
        else:
            failed = item.model_copy(
                update={
                    "status": WorkStatus.QUEUED,
                    "available_at": now + retry_delay(item.attempts, self._options),
                    "claimed_by": None,
                    "lease_expires_at": None,
                    "last_error": error,
                    "updated_at": now,
                }
            )
        await self._storage.write_item(ctx.org_id, failed)
        return failed

    async def defer(self, ctx: OpContext, item: WorkItem, delay: timedelta) -> WorkItem:
        return await self._hand_back(ctx, item, delay)

    async def release(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        return await self._hand_back(ctx, item, timedelta(0))

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        ctx.require(Permission.WRITE)
        stored = await self._storage.read_item(ctx.org_id, item.id)
        if (
            stored is None
            or stored.status is not WorkStatus.CLAIMED
            or stored.claimed_by != item.claimed_by
        ):
            raise LeaseLost(f"work item {item.id} is no longer held by {item.claimed_by}")
        now = utcnow()
        extended = stored.model_copy(update={"lease_expires_at": now + lease, "updated_at": now})
        await self._storage.write_item(ctx.org_id, extended)
        return extended

    async def requeue_stale(self) -> int:
        now = utcnow()
        count = 0
        for index, (org_id, item) in enumerate(await self._storage.read_stale(now)):
            if item.attempts >= item.max_attempts:
                update = {"status": WorkStatus.FAILED, "last_error": "lease expired"}
            else:
                update = {
                    "status": WorkStatus.QUEUED,
                    "available_at": now + self._options.stale_stagger * index,
                    "last_error": "lease expired",
                }
            requeued = item.model_copy(
                update={**update, "claimed_by": None, "lease_expires_at": None, "updated_at": now}
            )
            await self._storage.write_item(org_id, requeued)
            count += 1
        if count:
            log.info("requeued %d stale work items", count)
        return count

    async def maintenance_contexts(self) -> list[OpContext]:
        return await self._tenancy.service_contexts(
            AppContext(type=AppType.WORKER, version="worker@maintenance"), new_id()
        )

    async def _hand_back(self, ctx: OpContext, item: WorkItem, delay: timedelta) -> WorkItem:
        ctx.require(Permission.WRITE)
        now = utcnow()
        returned = item.model_copy(
            update={
                "status": WorkStatus.QUEUED,
                "available_at": now + delay,
                "claimed_by": None,
                "lease_expires_at": None,
                "attempts": max(0, item.attempts - 1),
                "updated_at": now,
            }
        )
        await self._storage.write_item(ctx.org_id, returned)
        return returned
