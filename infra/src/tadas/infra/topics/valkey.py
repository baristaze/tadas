import asyncio
import contextlib
import json
import logging
from collections.abc import Callable

from glide import GlideClient, GlideClientConfiguration

from tadas.infra.impl.valkey import ValkeyConnection
from tadas.infra.topics import TOPIC_PAYLOADS, TopicHandler, TopicPayload, Topics, TopicsInterface
from tadas.infra.topics.dispatch import LocalSubscribers, check_payload

log = logging.getLogger(__name__)


class TopicsValkeyImpl(TopicsInterface):
    """Pub/sub on the cache: every subscribed process receives every publish.
    Publishing uses the shared client; listening uses a client of its own,
    subscribed at creation so GLIDE restores the subscription on reconnect."""

    def __init__(self, connection: ValkeyConnection, channel_prefix: str = "tadas:topics:") -> None:
        self._connection = connection
        self._prefix = channel_prefix
        self._subscribers = LocalSubscribers()
        self._subscriber: GlideClient | None = None
        self._listener: asyncio.Task[None] | None = None

    async def publish(self, topic: Topics, payload: TopicPayload) -> None:
        check_payload(topic, payload)
        client = await self._connection.client()
        if client is None:
            raise RuntimeError("topics publish after the infra root closed")
        await client.publish(payload.model_dump_json(), self._prefix + topic.value)

    def subscribe(self, topic: Topics, consumer: str, handler: TopicHandler) -> Callable[[], None]:
        return self._subscribers.add(topic, consumer, handler)

    async def start(self) -> None:
        modes = GlideClientConfiguration.PubSubChannelModes
        subscriptions = GlideClientConfiguration.PubSubSubscriptions(
            channels_and_patterns={modes.Pattern: {self._prefix + "*"}},
            callback=None,
            context=None,
        )
        self._subscriber = await GlideClient.create(self._connection.configuration(subscriptions))
        self._listener = asyncio.create_task(self._listen(), name="topics-valkey-listener")

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None
        if self._subscriber is not None:
            await self._subscriber.close()
            self._subscriber = None

    async def _listen(self) -> None:
        assert self._subscriber is not None
        while True:
            message = await self._subscriber.get_pubsub_message()
            channel = message.channel
            channel = channel.decode() if isinstance(channel, bytes) else str(channel)
            try:
                topic = Topics(channel[len(self._prefix) :])
                data = message.message
                text = data.decode() if isinstance(data, bytes) else str(data)
                payload = TOPIC_PAYLOADS[topic].model_validate(json.loads(text))
            except ValueError, KeyError:
                log.warning("ignoring malformed message on %s", channel)
                continue
            await self._subscribers.dispatch(topic, payload)

    def describe(self) -> str:
        return "topics=valkey"
