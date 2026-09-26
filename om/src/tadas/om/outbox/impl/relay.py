import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from tadas.infra.observability import OUTCOMES
from tadas.infra.topics import EntityChangedPayload, Topics, TopicsInterface
from tadas.om.base import Platform, new_id, utcnow
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event
from tadas.om.outbox.relay import OutboxRelayInterface
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.work import WorkManagerInterface
from tadas.om.work.types.work_item import asks_for_work

log = logging.getLogger(__name__)

DEAD_LETTER_KIND = "outbox.row.failed"
"""The audit event a row whose attempts are spent leaves in the tenant's stream."""


class OutboxOptions(Platform):
    grace: timedelta = timedelta(seconds=10)
    """A row younger than this is the request path's to relay; the sweep leaves it."""
    backoff_base: timedelta = timedelta(seconds=30)
    backoff_cap: timedelta = timedelta(minutes=15)
    max_attempts: int = 10
    """Past this many sweep attempts the row is a dead letter."""


class OutboxRelayImpl(OutboxRelayInterface):
    def __init__(
        self,
        storage: OutboxStorageInterface,
        events: EventStorageInterface,
        topics: TopicsInterface,
        work: Callable[[], WorkManagerInterface] | None = None,
        options: OutboxOptions | None = None,
    ) -> None:
        """`work` is a provider and not the manager itself: the work manager needs
        the tenancy manager, which needs this relay, so the root binds the edge
        at call time and hands back one whole graph. A relay built without one
        relays entity changes and refuses a row that asks for work."""
        self._storage = storage
        self._events = events
        self._topics = topics
        self._work = work
        self._options = options or OutboxOptions()

    async def relay(self, org_id: UUID, row: OutboxRow) -> bool:
        try:
            await self._deliver(org_id, row)
        except Exception:
            # The row is durable; the sweep relays it again. The request that
            # wrote it has already succeeded and is not failed for a bus hiccup.
            log.exception("outbox relay of %s (%s) failed; the sweep retries", row.id, row.kind)
            OUTCOMES.labels(subsystem="outbox", outcome="relay_failed").inc()
            return False
        OUTCOMES.labels(subsystem="outbox", outcome="relayed").inc()
        return True

    async def relay_pending(self, limit: int) -> int:
        now = utcnow()
        options = self._options
        claimed = await self._storage.claim_pending(
            limit, now, options.grace, options.backoff_base, options.backoff_cap
        )
        relayed = 0
        for row in claimed:
            try:
                await self._deliver(row.org_id, row)
            except Exception as error:
                await self._failed(row.org_id, row, f"{type(error).__name__}: {error}"[:500], now)
                continue
            OUTCOMES.labels(subsystem="outbox", outcome="relayed").inc()
            relayed += 1
        if relayed:
            log.info("outbox sweep relayed %d rows", relayed)
        return relayed

    async def purge_done(self, retention: timedelta, limit: int) -> int:
        purged = await self._storage.purge_done(utcnow() - retention, limit)
        if purged:
            OUTCOMES.labels(subsystem="outbox", outcome="purged").inc(purged)
        return purged

    async def _deliver(self, org_id: UUID, row: OutboxRow) -> None:
        """The row's kind is its destination: an entity change becomes an event and
        an ENTITY_CHANGED publish, and a row of kind `work.<kind>`, the one a
        write that also starts work landed beside its entity's row, becomes a
        row in the queue and a WORK_AVAILABLE publish. Then the row is marked
        done. Raises on any step, and every step is safe to run again: the
        event is idempotent on the row's id and so is the enqueue, which
        presents that id as the item's key."""
        if asks_for_work(row.kind):
            await self._enqueue(org_id, row)
            await self._storage.mark_done(org_id, row.id)
            return
        # The event's id is the row's id: the append is idempotent on it, so a
        # second relay of the same row gets the same event back, same seq.
        event = Event(
            id=row.id,
            org_id=row.org_id,
            kind=row.kind,
            target_id=row.target_id,
            payload=row.payload,
            produced_at=row.created_at,
            actor_id=row.actor_id,
            request_id=row.request_id,
            app=row.app,
        )
        appended = await self._events.append_event(org_id, event)
        await self._publish(org_id, appended)
        await self._storage.mark_done(org_id, row.id)

    async def _enqueue(self, org_id: UUID, row: OutboxRow) -> None:
        """The work item the row asks for, enqueued with no context: the relay has
        no principal, so the manager stamps the actor from the row."""
        if self._work is None:
            raise RuntimeError("this relay was built without a work manager to enqueue into")
        await self._work().enqueue_relayed(org_id, row)

    async def _failed(self, org_id: UUID, row: OutboxRow, error: str, now: datetime) -> None:
        """One sweep attempt failed: the claim already set the next attempt, so
        the row keeps its error and waits, and nothing behind it waits with it.
        Once the attempts are spent the row is a dead letter: failed for good,
        counted, and named by an audit event in the tenant's stream, best
        effort, since the stream may be what is failing."""
        OUTCOMES.labels(subsystem="outbox", outcome="relay_failed").inc()
        if row.attempts < self._options.max_attempts:
            log.warning(
                "outbox relay of %s (%s) failed on attempt %d: %s",
                row.id,
                row.kind,
                row.attempts,
                error,
            )
            await self._storage.record_failure(org_id, row.id, error, None)
            return
        log.error(
            "outbox row %s (%s) failed for good after %d attempts: %s",
            row.id,
            row.kind,
            row.attempts,
            error,
        )
        await self._storage.record_failure(org_id, row.id, error, now)
        OUTCOMES.labels(subsystem="outbox", outcome="dead_letter").inc()
        audit = Event(
            id=new_id(),
            org_id=row.org_id,
            kind=DEAD_LETTER_KIND,
            target_id=row.id,
            payload={
                "kind": row.kind,
                "row_target_id": str(row.target_id),
                "attempts": row.attempts,
                "last_error": error,
            },
            produced_at=now,
            actor_id=row.actor_id,
            request_id=row.request_id,
            app=row.app,
        )
        try:
            await self._publish(org_id, await self._events.append_event(org_id, audit))
        except Exception:
            log.exception("the dead letter audit event for %s could not be appended", row.id)

    async def _publish(self, org_id: UUID, appended: Event) -> None:
        await self._topics.publish(
            Topics.ENTITY_CHANGED,
            EntityChangedPayload(
                idempotency_key=appended.id,
                produced_at=appended.produced_at,
                org_id=org_id,
                kind=appended.kind,
                target_id=appended.target_id,
                seq=appended.seq,
                actor_id=appended.actor_id,
            ),
        )
