"""Infrastructure is fronted by a single root so consumers can ask for what
they need. The root has a lifecycle because some capabilities do."""

from typing import Protocol, runtime_checkable

from tadas.infra.buckets import BucketsInterface
from tadas.infra.cache import CacheInterface, CacheScope
from tadas.infra.queues import QueueInterface
from tadas.infra.secrets import SecretsInterface
from tadas.infra.topics import TopicsInterface


@runtime_checkable
class HasLifecycle(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...


class InfraInterface:
    def get_cache(self, scope: CacheScope) -> CacheInterface: ...

    def get_buckets(self) -> BucketsInterface: ...

    def get_topics(self) -> TopicsInterface: ...

    def get_queues(self) -> QueueInterface: ...

    def get_secrets(self) -> SecretsInterface: ...

    def describe(self) -> list[str]:
        """One line per chosen backend, logged once at boot."""
        ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...
