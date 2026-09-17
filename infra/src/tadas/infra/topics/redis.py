import asyncio
import contextlib
import json
import logging
from collections.abc import Callable

from redis.asyncio import Redis

from tadas.infra.topics import TOPIC_PAYLOADS, TopicHandler, TopicPayload, Topics, TopicsInterface
from tadas.infra.topics.dispatch import LocalSubscribers, check_payload

log = logging.getLogger(__name__)


class TopicsRedisImpl(TopicsInterface):
    """Pub/sub on the cache: every subscribed process receives every publish."""

    def __init__(self, redis: Redis, channel_prefix: str = "tadas:topics:") -> None:
        self._redis = redis
        self._prefix = channel_prefix
        self._subscribers = LocalSubscribers()
        self._pubsub = None
        self._listener: asyncio.Task[None] | None = None

    async def publish(self, topic: Topics, payload: TopicPayload) -> None:
        check_payload(topic, payload)
        await self._redis.publish(self._prefix + topic.value, payload.model_dump_json())

    def subscribe(self, topic: Topics, consumer: str, handler: TopicHandler) -> Callable[[], None]:
        return self._subscribers.add(topic, consumer, handler)

    async def start(self) -> None:
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await self._pubsub.psubscribe(self._prefix + "*")
        self._listener = asyncio.create_task(self._listen(), name="topics-redis-listener")

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None
        if self._pubsub is not None:
            await self._pubsub.aclose()
            self._pubsub = None

    async def _listen(self) -> None:
        assert self._pubsub is not None
        async for message in self._pubsub.listen():
            if message.get("type") != "pmessage":
                continue
            channel = message["channel"]
            channel = channel.decode() if isinstance(channel, bytes) else channel
            try:
                topic = Topics(channel[len(self._prefix) :])
                payload = TOPIC_PAYLOADS[topic].model_validate(json.loads(message["data"]))
            except ValueError, KeyError:
                log.warning("ignoring malformed message on %s", channel)
                continue
            await self._subscribers.dispatch(topic, payload)

    def describe(self) -> str:
        return "topics=redis"
