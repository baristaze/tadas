from datetime import timedelta

from tadas.infra.queues import Queues
from tadas.infra.queues.memory import QueueMemoryImpl

NO_WAIT = timedelta(0)


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


async def test_dead_letters_are_visible_in_depth() -> None:
    queue = QueueMemoryImpl(max_receives=2)
    await queue.send(Queues.WEBHOOKS, b"poison")
    for _ in range(2):
        assert len(await queue.receive(Queues.WEBHOOKS, 1, NO_WAIT, timedelta(seconds=-1))) == 1
    assert await queue.receive(Queues.WEBHOOKS, 1, NO_WAIT, timedelta(seconds=-1)) == []
    depth = await queue.depth(Queues.WEBHOOKS)
    assert depth.dead_lettered == 1 and depth.visible == 0


async def test_dedup_id_returns_the_original_message() -> None:
    queue = QueueMemoryImpl()
    first = await queue.send(Queues.WEBHOOKS, b"x", dedup_id="delivery-1")
    second = await queue.send(Queues.WEBHOOKS, b"x", dedup_id="delivery-1")
    assert first == second
    assert (await queue.depth(Queues.WEBHOOKS)).visible == 1
