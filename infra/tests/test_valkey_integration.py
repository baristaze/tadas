"""The Valkey cache and topics impls over the compose stack's Valkey, through
the configured infra root a process builds."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest

from tadas.infra.cache import CacheScope
from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.impl.settings import InfraSettings
from tadas.infra.topics import TopicPayload, Topics, WorkAvailablePayload
from tadas.om.base import EMPTY_UUID, new_id, utcnow

pytestmark = pytest.mark.integration


@pytest.fixture
async def infra() -> AsyncIterator[InfraConfiguredImpl]:
    settings = InfraSettings.model_validate(
        {
            "environment": "local",
            "cache_backend": "valkey",
            "topics_backend": "valkey",
            "valkey_url": InfraSettings().valkey_url,
        }
    )
    root = InfraConfiguredImpl(settings)
    await root.start()
    try:
        yield root
    finally:
        await root.close()


async def test_put_get_invalidate_and_tenant_scoping(infra: InfraConfiguredImpl) -> None:
    cache = infra.get_cache(CacheScope.NETWORK_RESPONSE)
    org_a, org_b = new_id(), new_id()
    await cache.put(org_a, "k", b"a", timedelta(seconds=30))
    await cache.put(EMPTY_UUID, "k", b"system", timedelta(seconds=30))
    assert await cache.get(org_a, "k") == b"a"
    assert await cache.get(org_b, "k") is None
    assert await cache.get(EMPTY_UUID, "k") == b"system"
    await cache.invalidate(org_a, "k")
    assert await cache.get(org_a, "k") is None


async def test_entries_expire(infra: InfraConfiguredImpl) -> None:
    cache = infra.get_cache(CacheScope.NETWORK_RESPONSE)
    org = new_id()
    await cache.put(org, "k", b"v", timedelta(milliseconds=50))
    await asyncio.sleep(0.2)
    assert await cache.get(org, "k") is None


async def test_increment_counts_within_a_window(infra: InfraConfiguredImpl) -> None:
    cache = infra.get_cache(CacheScope.RATE_LIMIT)
    org = new_id()
    count, remaining = await cache.increment(org, "login", timedelta(seconds=60))
    assert count == 1 and timedelta(seconds=59) < remaining <= timedelta(seconds=60)
    count, _ = await cache.increment(org, "login", timedelta(seconds=60))
    assert count == 2


async def test_a_publish_reaches_a_subscriber(infra: InfraConfiguredImpl) -> None:
    topics = infra.get_topics()
    received: asyncio.Queue[TopicPayload] = asyncio.Queue()

    async def handler(payload: TopicPayload) -> None:
        await received.put(payload)

    topics.subscribe(Topics.WORK_AVAILABLE, "test", handler)
    sent = WorkAvailablePayload(
        idempotency_key=new_id(),
        produced_at=utcnow(),
        org_id=new_id(),
        queue="default",
        kind="NOOP",
    )
    # The subscriber connects lazily; publish until the subscription is live.
    for _ in range(50):
        await topics.publish(Topics.WORK_AVAILABLE, sent)
        try:
            got = await asyncio.wait_for(received.get(), timeout=0.1)
        except TimeoutError:
            continue
        assert got == sent
        return
    pytest.fail("no message arrived")


async def test_a_cache_read_works_without_start() -> None:
    """The worker's health probe reads the liveness key without starting the root."""
    settings = InfraSettings.model_validate(
        {
            "environment": "local",
            "cache_backend": "valkey",
            "valkey_url": InfraSettings().valkey_url,
        }
    )
    writer, probe = InfraConfiguredImpl(settings), InfraConfiguredImpl(settings)
    org = new_id()
    try:
        await writer.get_cache(CacheScope.WORKER_LIVENESS).put(
            org, "k", b"v", timedelta(seconds=30)
        )
        assert await probe.get_cache(CacheScope.WORKER_LIVENESS).get(org, "k") == b"v"
    finally:
        await writer.close()
        await probe.close()
