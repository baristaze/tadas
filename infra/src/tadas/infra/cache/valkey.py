import logging
from datetime import timedelta
from uuid import UUID

from glide import ExpirySet, ExpiryType, GlideClient, GlideError

from tadas.infra.cache import CacheInterface, CacheScope, cache_key
from tadas.infra.impl.valkey import ValkeyConnection
from tadas.infra.observability import OUTCOMES

log = logging.getLogger(__name__)


class _Unreachable(Exception):
    """No client: the root has closed."""


class CacheValkeyImpl(CacheInterface):
    """A backend that cannot be reached is a miss, not an error. The client
    is owned by the infra root, so this impl has no lifecycle of its own."""

    def __init__(self, connection: ValkeyConnection, scope: CacheScope) -> None:
        self._connection = connection
        self._scope = scope

    def _key(self, org_id: UUID, key: str) -> str:
        return f"tadas:cache:{self._scope.value}:{cache_key(org_id, key)}"

    async def _client(self) -> GlideClient:
        client = await self._connection.client()
        if client is None:
            raise _Unreachable
        return client

    async def get(self, org_id: UUID, key: str) -> bytes | None:
        try:
            client = await self._client()
            value = await client.get(self._key(org_id, key))
        except GlideError, _Unreachable:
            self._unreachable("get")
            return None
        OUTCOMES.labels(subsystem="cache", outcome="miss" if value is None else "hit").inc()
        return value

    async def put(self, org_id: UUID, key: str, value: bytes, ttl: timedelta) -> None:
        try:
            client = await self._client()
            await client.set(
                self._key(org_id, key), value, expiry=ExpirySet(ExpiryType.MILLSEC, _millis(ttl))
            )
        except GlideError, _Unreachable:
            self._unreachable("put")

    async def invalidate(self, org_id: UUID, key: str) -> None:
        try:
            client = await self._client()
            await client.delete([self._key(org_id, key)])
        except GlideError, _Unreachable:
            self._unreachable("invalidate")

    async def increment(self, org_id: UUID, key: str, ttl: timedelta) -> tuple[int, timedelta]:
        full_key = self._key(org_id, key)
        try:
            client = await self._client()
            count = await client.incr(full_key)
            remaining = await client.pttl(full_key)
            if remaining < 0:
                await client.pexpire(full_key, _millis(ttl))
                remaining = _millis(ttl)
        except GlideError, _Unreachable:
            self._unreachable("increment")
            return 0, ttl
        return count, timedelta(milliseconds=remaining)

    def describe(self) -> str:
        return f"cache[{self._scope.value}]=valkey"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def _unreachable(self, operation: str) -> None:
        OUTCOMES.labels(subsystem="cache", outcome="unreachable").inc()
        log.warning("cache %s unreachable on %s; treating as a miss", self._scope.value, operation)


def _millis(ttl: timedelta) -> int:
    return max(1, int(ttl.total_seconds() * 1000))
