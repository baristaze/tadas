"""Queues: work whose producer is outside the platform and cannot be told to
wait. At-least-once, no deduplication; the consumer is idempotent."""

from abc import ABC, abstractmethod
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


class QueueInterface(ABC):
    @abstractmethod
    async def send(self, queue: Queues, body: bytes, *, dedup_id: str | None = None) -> str: ...

    @abstractmethod
    async def receive(
        self, queue: Queues, max_messages: int, wait: timedelta, visibility: timedelta
    ) -> list[QueueMessage]: ...

    @abstractmethod
    async def delete(self, queue: Queues, receipt: str) -> None: ...

    @abstractmethod
    async def change_visibility(
        self, queue: Queues, receipt: str, visibility: timedelta
    ) -> None: ...

    @abstractmethod
    async def depth(self, queue: Queues) -> QueueDepth: ...

    @abstractmethod
    def describe(self) -> str: ...

    @abstractmethod
    async def start(self) -> None:
        """Opened by the infra root at boot. An impl that holds no connection
        of its own returns None."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Closed by the infra root at shutdown, in reverse order of start."""
        ...
