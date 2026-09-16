from collections.abc import Callable

from tadas.infra.topics import TopicHandler, TopicPayload, Topics, TopicsInterface
from tadas.infra.topics.dispatch import LocalSubscribers, check_payload


class TopicsMemoryImpl(TopicsInterface):
    """An in-process dispatcher: at-least-once to every handler subscribed now."""

    def __init__(self) -> None:
        self._subscribers = LocalSubscribers()

    async def publish(self, topic: Topics, payload: TopicPayload) -> None:
        check_payload(topic, payload)
        await self._subscribers.dispatch(topic, payload)

    def subscribe(self, topic: Topics, consumer: str, handler: TopicHandler) -> Callable[[], None]:
        return self._subscribers.add(topic, consumer, handler)

    def describe(self) -> str:
        return "topics=memory"
