"""The all-local infra root: every capability in-process or on disk under
one folder, for tests and the fast gate."""

from pathlib import Path

from tadas.infra.buckets import BucketsInterface
from tadas.infra.buckets.local import BucketsLocalImpl
from tadas.infra.cache import CacheInterface, CacheScope
from tadas.infra.cache.memory import CacheMemoryImpl
from tadas.infra.queues import QueueInterface
from tadas.infra.queues.memory import QueueMemoryImpl
from tadas.infra.root import InfraInterface
from tadas.infra.secrets import SecretsInterface
from tadas.infra.secrets.local import SecretsLocalImpl
from tadas.infra.topics import TopicsInterface
from tadas.infra.topics.memory import TopicsMemoryImpl


class InfraLocalImpl(InfraInterface):
    def __init__(self, root: Path) -> None:
        self._root = root
        self._caches: dict[CacheScope, CacheInterface] = {}
        self._buckets = BucketsLocalImpl(root / "buckets")
        self._topics = TopicsMemoryImpl()
        self._queues = QueueMemoryImpl()
        self._secrets = SecretsLocalImpl(root / "secrets.env")

    def get_cache(self, scope: CacheScope) -> CacheInterface:
        if scope not in self._caches:
            self._caches[scope] = CacheMemoryImpl(scope)
        return self._caches[scope]

    def get_buckets(self) -> BucketsInterface:
        return self._buckets

    def get_topics(self) -> TopicsInterface:
        return self._topics

    def get_queues(self) -> QueueInterface:
        return self._queues

    def get_secrets(self) -> SecretsInterface:
        return self._secrets

    def describe(self) -> list[str]:
        return [
            "cache=memory",
            self._topics.describe(),
            self._buckets.describe(),
            self._queues.describe(),
            self._secrets.describe(),
        ]

    async def start(self) -> None:
        for capability in (self._topics, self._buckets, self._queues, self._secrets):
            await capability.start()

    async def close(self) -> None:
        for cache in list(self._caches.values()):
            await cache.close()
        for capability in (self._secrets, self._queues, self._buckets, self._topics):
            await capability.close()
