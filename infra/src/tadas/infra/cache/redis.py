import logging
from datetime import timedelta
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from tadas.infra.cache import CacheInterface, CacheScope, cache_key
from tadas.infra.observability import OUTCOMES

log = logging.getLogger(__name__)


class CacheRedisImpl(CacheInterface):
    """A backend that cannot be reached is a miss, not an error. The client
    is owned by the infra root, so this impl has no lifecycle of its own."""

    def __init__(self, redis: Redis, scope: CacheScope) -> None:
        self._redis = redis
        self._scope = scope

    def _key(self, org_id: UUID, key: str) -> str:
        return f"tadas:cache:{self._scope.value}:{cache_key(org_id, key)}"

    async def get(self, org_id: UUID, key: str) -> bytes | None:
        try:
            value = await self._redis.get(self._key(org_id, key))
        except RedisError:
            self._unreachable("get")
            return None
        OUTCOMES.labels(subsystem="cache", outcome="miss" if value is None else "hit").inc()
        if isinstance(value, str):
            return value.encode()
        return value

    async def put(self, org_id: UUID, key: str, value: bytes, ttl: timedelta) -> None:
        try:
            await self._redis.set(self._key(org_id, key), value, px=_millis(ttl))
        except RedisError:
            self._unreachable("put")

    async def invalidate(self, org_id: UUID, key: str) -> None:
        try:
            await self._redis.delete(self._key(org_id, key))
        except RedisError:
            self._unreachable("invalidate")

    async def increment(self, org_id: UUID, key: str, ttl: timedelta) -> tuple[int, timedelta]:
        full_key = self._key(org_id, key)
        try:
            count = int(await self._redis.incr(full_key))
            remaining = int(await self._redis.pttl(full_key))
            if remaining < 0:
                await self._redis.pexpire(full_key, _millis(ttl))
                remaining = _millis(ttl)
        except RedisError:
            self._unreachable("increment")
            return 0, ttl
        return count, timedelta(milliseconds=remaining)

    def describe(self) -> str:
        return f"cache[{self._scope.value}]=redis"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def _unreachable(self, operation: str) -> None:
        OUTCOMES.labels(subsystem="cache", outcome="unreachable").inc()
        log.warning("cache %s unreachable on %s; treating as a miss", self._scope.value, operation)


def _millis(ttl: timedelta) -> int:
    return max(1, int(ttl.total_seconds() * 1000))
