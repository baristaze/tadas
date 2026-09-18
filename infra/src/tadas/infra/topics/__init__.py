"""Topics: wake-ups and live updates. Names are fixed by enum, payloads by
the payload map. A topic is best effort: a published event reaches every
process that was subscribed at the time, at most once, and a bus hiccup may
lose it. Durable work never rides a topic; it is a row in the work queue,
and a missed wake-up degrades to polling latency, never to lost work."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TopicPayload(BaseModel):
    """The frozen base every payload extends, declared here so the object
    model never has to be imported by the bus. A tolerant reader: a field
    the consumer does not know is ignored, so producers and consumers roll
    out in either order."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    idempotency_key: UUID  # uuid_v7, set by the producer
    produced_at: datetime
    org_id: UUID


class Topics(str, Enum):
    WORK_AVAILABLE = "work_available"
    ENTITY_CHANGED = "entity_changed"  # kind, target_id, seq: the realtime producer


class WorkAvailablePayload(TopicPayload):
    lane: str
    kind: str


class EntityChangedPayload(TopicPayload):
    """A record of `kind` changed; the socket is a hint and the record, at
    `seq` in the tenant's event stream, is the truth."""

    kind: str  # "<namespace>.<entity>.<created|updated|deleted>"
    target_id: UUID
    seq: int


TOPIC_PAYLOADS: dict[Topics, type[TopicPayload]] = {
    Topics.WORK_AVAILABLE: WorkAvailablePayload,
    Topics.ENTITY_CHANGED: EntityChangedPayload,
}

TopicHandler = Callable[[TopicPayload], Awaitable[None]]


class TopicsInterface:
    async def publish(self, topic: Topics, payload: TopicPayload) -> None: ...

    def subscribe(
        self,
        topic: Topics,
        consumer: str,
        handler: TopicHandler,
    ) -> Callable[[], None]:
        """Returns an unsubscribe callable."""
        ...

    def describe(self) -> str: ...

    async def start(self) -> None:
        """Opened by the infra root at boot. An impl that holds no connection
        of its own returns None."""
        ...

    async def close(self) -> None:
        """Closed by the infra root at shutdown, in reverse order of start."""
        ...
