"""The Valkey listener outlives the driver: a failed subscriber is counted,
logged, and reopened with backoff, and the next message still reaches its
handlers. The subscribers are injected; nothing here connects."""

import asyncio
import logging
from datetime import timedelta
from typing import Any

import pytest
from glide import GlideError
from prometheus_client import REGISTRY

from tadas.infra.base import new_id, utcnow
from tadas.infra.impl.valkey import ValkeyConnection
from tadas.infra.topics import TopicPayload, Topics, WorkAvailablePayload
from tadas.infra.topics.valkey import TopicsValkeyImpl


class Message:
    def __init__(self, channel: str, payload: TopicPayload) -> None:
        self.channel = channel.encode()
        self.message = payload.model_dump_json().encode()


class FailingSubscriber:
    """Every receive is the driver giving up."""

    closed = False

    async def get_pubsub_message(self) -> Any:
        raise GlideError("connection reset by the server")

    async def close(self) -> None:
        self.closed = True


class DeliveringSubscriber:
    """Hands out its messages, then waits until closed."""

    def __init__(self, messages: list[Message]) -> None:
        self._messages = list(messages)
        self._closed = asyncio.Event()

    async def get_pubsub_message(self) -> Any:
        if self._messages:
            return self._messages.pop(0)
        await self._closed.wait()
        raise GlideError("closed")

    async def close(self) -> None:
        self._closed.set()


def failures_counted() -> float:
    return (
        REGISTRY.get_sample_value(
            "tadas_outcomes_total", {"subsystem": "topics", "outcome": "listener_failed"}
        )
        or 0.0
    )


async def test_a_failed_listener_reconnects_and_keeps_delivering(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sent = WorkAvailablePayload(
        idempotency_key=new_id(), produced_at=utcnow(), org_id=new_id(), lane="default", kind="NOOP"
    )
    first = FailingSubscriber()
    second = DeliveringSubscriber([Message("tadas:topics:work_available", sent)])
    subscribers: list[Any] = [first, second]
    opened: list[Any] = []

    async def open_next(self: TopicsValkeyImpl) -> Any:
        subscriber = subscribers.pop(0)
        opened.append(subscriber)
        return subscriber

    monkeypatch.setattr(TopicsValkeyImpl, "_open_subscriber", open_next)
    monkeypatch.setattr(TopicsValkeyImpl, "RECONNECT_BACKOFF_SECONDS", (0.01,))
    topics = TopicsValkeyImpl(ValkeyConnection("valkey://127.0.0.1:1/0", timedelta(seconds=1)))
    received: asyncio.Queue[TopicPayload] = asyncio.Queue()

    async def handler(payload: TopicPayload) -> None:
        await received.put(payload)

    topics.subscribe(Topics.WORK_AVAILABLE, "test", handler)
    before = failures_counted()
    with caplog.at_level(logging.WARNING, logger="tadas.infra.topics.valkey"):
        await topics.start()
        got = await asyncio.wait_for(received.get(), timeout=2)
    await topics.close()

    assert got == sent
    assert opened == [first, second] and first.closed
    assert failures_counted() == before + 1
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        "topics listener failed (GlideError: connection reset by the server); reconnecting in 0.0s"
    ]
