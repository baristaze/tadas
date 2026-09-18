"""Queues: work whose producer is outside the platform and cannot be told to
wait. At-least-once, no deduplication; the consumer is idempotent."""

from datetime import timedelta
from enum import Enum

from tadas.infra.base import InfraModel


class Queues(str, Enum):
    WEBHOOKS = "webhooks"


class QueueMessage(InfraModel):
    id: str
    body: bytes
    receipt: str
    attempts: int


class QueueDepth(InfraModel):
    visible: int
    in_flight: int
    dead_lettered: int


class QueueInterface:
    async def send(self, queue: Queues, body: bytes, *, dedup_id: str | None = None) -> str: ...

    async def receive(
        self, queue: Queues, max_messages: int, wait: timedelta, visibility: timedelta
    ) -> list[QueueMessage]: ...

    async def delete(self, queue: Queues, receipt: str) -> None: ...

    async def change_visibility(
        self, queue: Queues, receipt: str, visibility: timedelta
    ) -> None: ...

    async def depth(self, queue: Queues) -> QueueDepth: ...

    def describe(self) -> str: ...

    async def start(self) -> None:
        """Opened by the infra root at boot. An impl that holds no connection
        of its own returns None."""
        ...

    async def close(self) -> None:
        """Closed by the infra root at shutdown, in reverse order of start."""
        ...
