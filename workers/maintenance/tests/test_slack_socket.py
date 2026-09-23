"""The Socket Mode bridge acknowledges before anything else happens, queues
each delivery once, and drops Slack's retries by the delivery's key."""

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from tadas.infra.queues import Queues
from tadas.infra.queues.memory import QueueMemoryImpl
from tadas.workers.maintenance.slack_inbound import InboundDelivery
from tadas.workers.maintenance.slack_socket import SlackSocketBridge


@dataclass(frozen=True)
class Request:
    envelope_id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


class SlowQueue(QueueMemoryImpl):
    """A queue whose send waits until the test lets it through."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def send(self, queue: Queues, body: bytes) -> None:
        await self.release.wait()
        await super().send(queue, body)


class BrokenQueue(QueueMemoryImpl):
    async def send(self, queue: Queues, body: bytes) -> None:
        raise ConnectionError("queue down")


async def received(queues: QueueMemoryImpl) -> list[InboundDelivery]:
    messages = await queues.receive(Queues.SLACK, 10, timedelta(0), timedelta(seconds=30))
    return [InboundDelivery.model_validate_json(message.body) for message in messages]


async def test_the_ack_goes_back_before_the_delivery_is_queued() -> None:
    queues = SlowQueue()
    bridge = SlackSocketBridge(queues)
    acked: list[str] = []

    async def ack(envelope_id: str) -> None:
        acked.append(envelope_id)

    command = Request("env-1", "slash_commands", {"command": "/tadas", "text": "help"})
    handling = asyncio.create_task(bridge.on_request(ack, command))
    await asyncio.sleep(0.01)
    assert acked == ["env-1"], "acknowledged while the queue still holds the send"
    assert await received(queues) == []
    queues.release.set()
    await handling
    [delivery] = await received(queues)
    assert delivery.type == "slash_commands" and delivery.payload["text"] == "help"


async def test_a_retry_of_an_event_is_acknowledged_and_dropped() -> None:
    queues = QueueMemoryImpl()
    bridge = SlackSocketBridge(queues)
    acked: list[str] = []

    async def ack(envelope_id: str) -> None:
        acked.append(envelope_id)

    event = {"event_id": "Ev42", "event": {"type": "app_mention"}}
    await bridge.on_request(ack, Request("env-1", "events_api", event))
    await bridge.on_request(ack, Request("env-2", "events_api", event))  # Slack's retry
    assert acked == ["env-1", "env-2"], "every envelope is acknowledged"
    assert len(await received(queues)) == 1


async def test_a_queue_that_is_down_never_withholds_the_ack() -> None:
    bridge = SlackSocketBridge(BrokenQueue())
    acked: list[str] = []

    async def ack(envelope_id: str) -> None:
        acked.append(envelope_id)

    await bridge.on_request(ack, Request("env-9", "slash_commands", {"text": "help"}))
    assert acked == ["env-9"]
