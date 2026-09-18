import logging
from datetime import timedelta
from uuid import UUID

from tadas.infra.observability import OUTCOMES
from tadas.infra.topics import EntityChangedPayload, Topics, TopicsInterface
from tadas.om.base import utcnow
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event
from tadas.om.outbox.relay import OutboxRelayInterface
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.types.row import OutboxRow

log = logging.getLogger(__name__)


class OutboxRelayImpl(OutboxRelayInterface):
    def __init__(
        self,
        storage: OutboxStorageInterface,
        events: EventStorageInterface,
        topics: TopicsInterface,
    ) -> None:
        self._storage = storage
        self._events = events
        self._topics = topics

    async def relay(self, org_id: UUID, row: OutboxRow) -> bool:
        # The event's id is the row's id: the append is idempotent on it, so a
        # second relay of the same row gets the same event back, same seq.
        event = Event(
            id=row.id,
            kind=row.kind,
            target_id=row.target_id,
            payload=row.payload,
            produced_at=row.created_at,
            actor_id=row.actor_id,
            request_id=row.request_id,
            app=row.app,
        )
        try:
            appended = await self._events.append(org_id, event)
            await self._topics.publish(
                Topics.ENTITY_CHANGED,
                EntityChangedPayload(
                    idempotency_key=row.id,
                    produced_at=appended.produced_at,
                    org_id=org_id,
                    kind=appended.kind,
                    target_id=appended.target_id,
                    seq=appended.seq,
                ),
            )
            await self._storage.mark_done(org_id, row.id)
        except Exception:
            # The row is durable; the sweep relays it again. The request that
            # wrote it has already succeeded and is not failed for a bus hiccup.
            log.exception("outbox relay of %s (%s) failed; the sweep retries", row.id, row.kind)
            OUTCOMES.labels(subsystem="outbox", outcome="relay_failed").inc()
            return False
        OUTCOMES.labels(subsystem="outbox", outcome="relayed").inc()
        return True

    async def relay_pending(self, limit: int) -> int:
        relayed = 0
        for org_id, row in await self._storage.read_pending(limit):
            if await self.relay(org_id, row):
                relayed += 1
        if relayed:
            log.info("outbox sweep relayed %d rows", relayed)
        return relayed

    async def purge_done(self, retention: timedelta) -> int:
        purged = await self._storage.purge_done(utcnow() - retention)
        if purged:
            OUTCOMES.labels(subsystem="outbox", outcome="purged").inc(purged)
        return purged
