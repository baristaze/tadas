"""Topics: wake-ups and live updates. Names are fixed by enum, payloads by
the payload map, delivery is at-least-once to every subscribed process.
Durable work never rides a topic; it is a row in the work queue."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import Enum
from uuid import UUID

from tadas.om.base import Platform


class TopicPayload(Platform):
    idempotency_key: UUID  # uuid_v7, set by the producer
    produced_at: datetime
    org_id: UUID


class Topics(str, Enum):
    WORK_AVAILABLE = "work_available"
    ENTITY_CHANGED = "entity_changed"


class WorkAvailablePayload(TopicPayload):
    queue: str
    kind: str


class EntityChangedPayload(TopicPayload):
    """A record of `entity` changed; the socket is a hint and the record is the truth."""

    entity: str
    entity_id: UUID
    action: str  # created | updated | deleted


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
