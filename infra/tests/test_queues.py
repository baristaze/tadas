from datetime import timedelta

import pytest

from tadas.infra.observability import OUTCOMES
from tadas.infra.queues import Queues
from tadas.infra.queues.memory import QueueMemoryImpl

NO_WAIT = timedelta(0)


def outcome(name: str) -> float:
    return OUTCOMES.labels(subsystem="queue", outcome=name)._value.get()


async def test_send_receive_delete() -> None:
    queue = QueueMemoryImpl()
    await queue.send(Queues.WEBHOOKS, b"one")
    received = await queue.receive(Queues.WEBHOOKS, 10, NO_WAIT, timedelta(seconds=30))
    assert [m.body for m in received] == [b"one"]
    assert (await queue.depth(Queues.WEBHOOKS)).in_flight == 1
    await queue.delete(Queues.WEBHOOKS, received[0].receipt)
    assert await queue.receive(Queues.WEBHOOKS, 10, NO_WAIT, timedelta(seconds=30)) == []


async def test_invisible_messages_come_back_after_the_timeout() -> None:
    queue = QueueMemoryImpl()
    await queue.send(Queues.WEBHOOKS, b"retry")
    first = await queue.receive(Queues.WEBHOOKS, 1, NO_WAIT, timedelta(seconds=-1))
    second = await queue.receive(Queues.WEBHOOKS, 1, NO_WAIT, timedelta(seconds=30))
    assert first[0].id == second[0].id
    assert second[0].attempts == 2
    await queue.change_visibility(Queues.WEBHOOKS, second[0].receipt, timedelta(seconds=-1))
    assert len(await queue.receive(Queues.WEBHOOKS, 1, NO_WAIT, timedelta(seconds=30))) == 1


async def test_dead_letters_are_visible_in_depth_the_log_and_the_metric(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue = QueueMemoryImpl(max_receives=2)
    message_id = await queue.send(Queues.WEBHOOKS, b"poison")
    for _ in range(2):
        assert len(await queue.receive(Queues.WEBHOOKS, 1, NO_WAIT, timedelta(seconds=-1))) == 1
    before = outcome("dead_lettered")
    with caplog.at_level("WARNING", logger="tadas.infra.queues.memory"):
        assert await queue.receive(Queues.WEBHOOKS, 1, NO_WAIT, timedelta(seconds=-1)) == []
    depth = await queue.depth(Queues.WEBHOOKS)
    assert depth.dead_lettered == 1 and depth.visible == 0
    assert outcome("dead_lettered") == before + 1
    assert any(
        message_id in r.getMessage() and "webhooks" in r.getMessage() for r in caplog.records
    )


async def test_dedup_id_does_not_deduplicate_like_the_hosted_queue() -> None:
    queue = QueueMemoryImpl()
    first = await queue.send(Queues.WEBHOOKS, b"x", dedup_id="delivery-1")
    second = await queue.send(Queues.WEBHOOKS, b"x", dedup_id="delivery-1")
    assert first != second
    assert (await queue.depth(Queues.WEBHOOKS)).visible == 2


async def test_every_outcome_is_counted() -> None:
    queue = QueueMemoryImpl()
    sent, received, deleted = outcome("sent"), outcome("received"), outcome("deleted")
    await queue.send(Queues.WEBHOOKS, b"m")
    messages = await queue.receive(Queues.WEBHOOKS, 10, NO_WAIT, timedelta(seconds=30))
    await queue.delete(Queues.WEBHOOKS, messages[0].receipt)
    assert (outcome("sent"), outcome("received"), outcome("deleted")) == (
        sent + 1,
        received + 1,
        deleted + 1,
    )
