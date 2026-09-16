"""The infra root that picks impls from settings and refuses combinations
that are only safe locally."""

import aioboto3
from redis.asyncio import Redis

from tadas.infra.buckets import BucketsInterface
from tadas.infra.buckets.local import BucketsLocalImpl
from tadas.infra.buckets.s3 import BucketsS3Impl
from tadas.infra.cache import CacheInterface, CacheScope
from tadas.infra.cache.memory import CacheMemoryImpl
from tadas.infra.cache.redis import CacheRedisImpl
from tadas.infra.impl.settings import InfraSettings
from tadas.infra.queues import QueueInterface
from tadas.infra.queues.memory import QueueMemoryImpl
from tadas.infra.queues.sqs import QueueSqsImpl
from tadas.infra.root import HasLifecycle, InfraInterface
from tadas.infra.secrets import SecretsInterface
from tadas.infra.secrets.aws import SecretsAwsImpl
from tadas.infra.secrets.local import SecretsLocalImpl
from tadas.infra.topics import TopicsInterface
from tadas.infra.topics.memory import TopicsMemoryImpl
from tadas.infra.topics.redis import TopicsRedisImpl
from tadas.om.exceptions import PlatformException


class UnsafeConfiguration(PlatformException):
    code = "unsafe_configuration"


UNSAFE_IN_CLOUD: tuple[tuple[str, str, str], ...] = (
    ("secrets_backend", "local", "TADAS_SECRETS_BACKEND"),
    ("cache_backend", "memory", "TADAS_CACHE_BACKEND"),
    ("topics_backend", "memory", "TADAS_TOPICS_BACKEND"),
    ("buckets_backend", "local", "TADAS_BUCKETS_BACKEND"),
    ("queues_backend", "memory", "TADAS_QUEUES_BACKEND"),
)


def refuse_unsafe(settings: InfraSettings) -> None:
    """Each refusal is a one-line check that exits naming the setting."""
    if not settings.is_cloud_environment:
        return
    for field, unsafe_value, env_name in UNSAFE_IN_CLOUD:
        if getattr(settings, field) == unsafe_value:
            raise UnsafeConfiguration(
                f"{env_name}={unsafe_value} is refused "
                f"when TADAS_ENVIRONMENT={settings.environment}"
            )


class InfraConfiguredImpl(InfraInterface):
    def __init__(self, settings: InfraSettings) -> None:
        refuse_unsafe(settings)
        self._settings = settings
        self._redis: Redis | None = None
        if settings.cache_backend == "redis" or settings.topics_backend == "redis":
            self._redis = Redis.from_url(settings.redis_url)
        self._aws = aioboto3.Session(
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.aws_region,
        )
        self._caches: dict[CacheScope, CacheInterface] = {}

        if settings.buckets_backend == "s3":
            self._buckets: BucketsInterface = BucketsS3Impl(
                self._aws,
                endpoint_url=settings.s3_endpoint_url,
                region=settings.aws_region,
                bucket_prefix=settings.s3_bucket_prefix,
            )
        else:
            self._buckets = BucketsLocalImpl(settings.buckets_root)

        if settings.topics_backend == "redis":
            assert self._redis is not None
            self._topics: TopicsInterface = TopicsRedisImpl(self._redis)
        else:
            self._topics = TopicsMemoryImpl()

        if settings.queues_backend == "sqs":
            self._queues: QueueInterface = QueueSqsImpl(
                self._aws,
                endpoint_url=settings.sqs_endpoint_url,
                region=settings.aws_region,
                queue_prefix=settings.sqs_queue_prefix,
            )
        else:
            self._queues = QueueMemoryImpl()

        if settings.secrets_backend == "aws":
            self._secrets: SecretsInterface = SecretsAwsImpl(
                self._aws, region=settings.aws_region, name_prefix=settings.secrets_name_prefix
            )
        else:
            self._secrets = SecretsLocalImpl(settings.secrets_file)

    def get_cache(self, scope: CacheScope) -> CacheInterface:
        if scope not in self._caches:
            if self._settings.cache_backend == "redis":
                assert self._redis is not None
                self._caches[scope] = CacheRedisImpl(self._redis, scope)
            else:
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
            f"cache={self._settings.cache_backend}",
            self._topics.describe(),
            self._buckets.describe(),
            self._queues.describe(),
            self._secrets.describe(),
        ]

    def _lifecycles(self) -> list[HasLifecycle]:
        return [
            c
            for c in (self._topics, self._buckets, self._queues, self._secrets)
            if isinstance(c, HasLifecycle)
        ]

    async def start(self) -> None:
        for capability in self._lifecycles():
            await capability.start()

    async def close(self) -> None:
        for capability in reversed(self._lifecycles()):
            await capability.close()
        if self._redis is not None:
            await self._redis.aclose()
