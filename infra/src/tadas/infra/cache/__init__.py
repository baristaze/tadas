"""Cache: fast reads against data that is expensive to fetch. Scoped so
unrelated consumers do not step on each other's keys; fails open."""

from datetime import timedelta
from enum import Enum
from uuid import UUID

from tadas.om.base import EMPTY_UUID


class CacheScope(str, Enum):
    NETWORK_RESPONSE = "network_response"
    RATE_LIMIT = "rate_limit"
    REALTIME_TICKET = "realtime_ticket"
    WORKER_LIVENESS = "worker_liveness"


def cache_key(org_id: UUID, key: str) -> str:
    """System keys and tenant keys live in disjoint namespaces."""
    if org_id == EMPTY_UUID:
        return f"system:{key}"
    return f"org:{org_id}:{key}"


class CacheInterface:
    async def get(self, org_id: UUID, key: str) -> bytes | None: ...

    async def put(self, org_id: UUID, key: str, value: bytes, ttl: timedelta) -> None: ...

    async def invalidate(self, org_id: UUID, key: str) -> None: ...

    async def increment(self, org_id: UUID, key: str, ttl: timedelta) -> tuple[int, timedelta]:
        """The one atomic primitive: the new count and the time left on the window."""
        ...

    def describe(self) -> str: ...
