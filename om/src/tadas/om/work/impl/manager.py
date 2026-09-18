import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from pydantic import ValidationError

from tadas.infra.observability import OUTCOMES
from tadas.infra.topics import EntityChangedPayload, Topics, TopicsInterface, WorkAvailablePayload
from tadas.om.base import Platform, new_id, utcnow
from tadas.om.events import EventsManagerInterface
from tadas.om.events.manager import audit_event
from tadas.om.exceptions import LeaseLost, NotFound, ValidationFailed
from tadas.om.opcontext import AppContext, AppType, OpContext, Permission
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.work.manager import WorkManagerInterface
from tadas.om.work.rules import attempts_after_hand_back, is_exhausted, retry_delay
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.types.work_item import WORK_PAYLOADS, WorkItem, WorkKind, WorkStatus

log = logging.getLogger(__name__)

DEAD_LETTER_KIND = "work.item.failed"
"""The audit event a dead letter leaves in the tenant's stream."""


class WorkOptions(Platform):
    base_retry_delay: timedelta = timedelta(seconds=30)
    max_retry_delay: timedelta = timedelta(minutes=15)
    stale_stagger: timedelta = timedelta(seconds=5)


class WorkManagerImpl(WorkManagerInterface):
    def __init__(
        self,
        storage: WorkStorageInterface,
        tenancy: TenancyManagerInterface,
        events: EventsManagerInterface,
        topics: TopicsInterface,
        options: WorkOptions,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._events = events
        self._topics = topics
        self._options = options

    async def enqueue(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        ctx.require(Permission.WRITE)
        try:
            WORK_PAYLOADS[item.kind].model_validate(item.payload)
        except ValidationError as error:
            raise ValidationFailed(f"payload of {item.kind.value} work: {error}"[:500]) from None
        await self._storage.write_item(ctx.org_id, item)
        await self._topics.publish(
            Topics.WORK_AVAILABLE,
            WorkAvailablePayload(
                idempotency_key=item.idempotency_key,
                produced_at=utcnow(),
                org_id=ctx.org_id,
                lane=item.lane,
                kind=item.kind.value,
            ),
        )
        return item

    async def claim(
        self, lane: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[OpContext, WorkItem] | None:
        found = await self._storage.claim_next(lane, kinds, worker_id, lease)
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
        exhausted = is_exhausted(item)
        if exhausted:
            update: dict[str, Any] = {"status": WorkStatus.FAILED}
        else:
            delay = retry_delay(
                item.attempts, self._options.base_retry_delay, self._options.max_retry_delay
            )
            update = {"status": WorkStatus.QUEUED, "available_at": now + delay}
        failed = await self._transition(
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
        if exhausted:
            await self._dead_letter(ctx, failed)
        return failed

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
            ctx.org_id, utcnow(), self._options.stale_stagger, ctx.user_id
        )
        if requeued:
            log.info("requeued %d stale work items in org %s", len(requeued), ctx.org_id)
        for item in requeued:
            if item.status is WorkStatus.FAILED:
                await self._dead_letter(ctx, item)
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
        worker named on it, then writes the transition conditionally on that claim
        (`claimed_by` in the statement itself): a worker whose lease has passed is
        refused with LeaseLost, a Conflict, and hands the item back without
        spending an attempt (the fencing token)."""
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
            ctx.org_id,
            item.claimed_by,
            item.model_copy(update={**update, "updated_by": ctx.user_id}),
        )
        if written is None:
            raise LeaseLost(f"work item {item.id} was taken from {item.claimed_by} mid-write")
        return written

    async def _dead_letter(self, ctx: OpContext, item: WorkItem) -> None:
        """A failed item is a dead letter: an audit event names it in the tenant's
        stream and a metric counts it. The queue row is in the `queue` role and the
        outbox in `core`, so this write follows the transition directly; a crash
        between the two loses the audit entry, never the dead letter itself."""
        OUTCOMES.labels(subsystem="work", outcome="dead_letter").inc()
        log.error(
            "work item %s (%s) failed for good: %s", item.id, item.kind.value, item.last_error
        )
        event = await self._events.append(
            ctx,
            audit_event(
                ctx,
                new_id(),
                DEAD_LETTER_KIND,
                item.id,
                {
                    "kind": item.kind.value,
                    "work_target_id": str(item.target_id),
                    "attempts": item.attempts,
                    "last_error": item.last_error,
                },
            ),
        )
        await self._topics.publish(
            Topics.ENTITY_CHANGED,
            EntityChangedPayload(
                idempotency_key=event.id,
                produced_at=event.produced_at,
                org_id=ctx.org_id,
                kind=event.kind,
                target_id=event.target_id,
                seq=event.seq,
            ),
        )
