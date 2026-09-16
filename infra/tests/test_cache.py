from datetime import timedelta

from tadas.infra.cache import CacheScope
from tadas.infra.cache.memory import CacheMemoryImpl
from tadas.om.base import EMPTY_UUID, new_id


async def test_put_get_invalidate() -> None:
    cache = CacheMemoryImpl(CacheScope.NETWORK_RESPONSE)
    org = new_id()
    assert await cache.get(org, "k") is None
    await cache.put(org, "k", b"v", timedelta(seconds=30))
    assert await cache.get(org, "k") == b"v"
    await cache.invalidate(org, "k")
    assert await cache.get(org, "k") is None


async def test_keys_are_tenant_scoped_and_system_scope_is_disjoint() -> None:
    cache = CacheMemoryImpl(CacheScope.NETWORK_RESPONSE)
    org_a, org_b = new_id(), new_id()
    await cache.put(org_a, "k", b"a", timedelta(seconds=30))
    await cache.put(EMPTY_UUID, "k", b"system", timedelta(seconds=30))
    assert await cache.get(org_b, "k") is None
    assert await cache.get(org_a, "k") == b"a"
    assert await cache.get(EMPTY_UUID, "k") == b"system"


async def test_expired_entries_are_misses() -> None:
    cache = CacheMemoryImpl(CacheScope.NETWORK_RESPONSE)
    org = new_id()
    await cache.put(org, "k", b"v", timedelta(seconds=-1))
    assert await cache.get(org, "k") is None


async def test_increment_counts_within_a_window() -> None:
    cache = CacheMemoryImpl(CacheScope.RATE_LIMIT)
    org = new_id()
    count, remaining = await cache.increment(org, "login", timedelta(seconds=60))
    assert count == 1 and remaining == timedelta(seconds=60)
    count, remaining = await cache.increment(org, "login", timedelta(seconds=60))
    assert count == 2 and remaining <= timedelta(seconds=60)
    assert (await cache.increment(new_id(), "login", timedelta(seconds=60)))[0] == 1
    assert cache.describe() == "cache[rate_limit]=memory"
