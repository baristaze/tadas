import pytest

from tadas.infra.topics import (
    EntityChangedPayload,
    TopicPayload,
    Topics,
    WorkAvailablePayload,
)
from tadas.infra.topics.memory import TopicsMemoryImpl
from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import ValidationFailed


def work_available() -> WorkAvailablePayload:
    return WorkAvailablePayload(
        idempotency_key=new_id(),
        produced_at=utcnow(),
        org_id=new_id(),
        queue="default",
        kind="NOOP",
    )


async def test_publish_reaches_every_subscriber_until_unsubscribed() -> None:
    topics = TopicsMemoryImpl()
    seen_a: list[TopicPayload] = []
    seen_b: list[TopicPayload] = []

    async def a(payload: TopicPayload) -> None:
        seen_a.append(payload)

    async def b(payload: TopicPayload) -> None:
        seen_b.append(payload)

    unsubscribe_a = topics.subscribe(Topics.WORK_AVAILABLE, "a", a)
    topics.subscribe(Topics.WORK_AVAILABLE, "b", b)
    first = work_available()
    await topics.publish(Topics.WORK_AVAILABLE, first)
    unsubscribe_a()
    await topics.publish(Topics.WORK_AVAILABLE, work_available())
    assert seen_a == [first]
    assert len(seen_b) == 2


async def test_a_failing_handler_does_not_stop_the_others() -> None:
    topics = TopicsMemoryImpl()
    seen: list[TopicPayload] = []

    async def boom(payload: TopicPayload) -> None:
        raise RuntimeError("boom")

    async def ok(payload: TopicPayload) -> None:
        seen.append(payload)

    topics.subscribe(Topics.WORK_AVAILABLE, "boom", boom)
    topics.subscribe(Topics.WORK_AVAILABLE, "ok", ok)
    await topics.publish(Topics.WORK_AVAILABLE, work_available())
    assert len(seen) == 1


async def test_payload_type_is_fixed_by_the_map() -> None:
    topics = TopicsMemoryImpl()
    wrong = EntityChangedPayload(
        idempotency_key=new_id(),
        produced_at=utcnow(),
        org_id=new_id(),
        entity="task",
        entity_id=new_id(),
        action="created",
    )
    with pytest.raises(ValidationFailed):
        await topics.publish(Topics.WORK_AVAILABLE, wrong)
