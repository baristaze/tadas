from datetime import timedelta

import pytest

from tadas.infra.base import new_id
from tadas.infra.cache import CacheScope
from tadas.infra.cache.valkey import CacheValkeyImpl
from tadas.infra.impl.valkey import ValkeyConnection

TIMEOUT = timedelta(seconds=5)


@pytest.mark.parametrize(
    "url,described",
    [
        ("valkey://127.0.0.1:56379/0", "valkey://127.0.0.1:56379/0"),
        ("valkeys://cache.example.test:6379/2", "valkeys://cache.example.test:6379/2"),
        ("valkey://localhost", "valkey://localhost:6379/0"),
        ("valkeys://user:p%40ss@cache.example.test/0", "valkeys://cache.example.test:6379/0"),
    ],
)
def test_the_url_is_parsed_without_connecting(url: str, described: str) -> None:
    connection = ValkeyConnection(url, TIMEOUT)
    assert connection.describe() == described


def test_every_request_is_bounded_by_the_timeout() -> None:
    configuration = ValkeyConnection(
        "valkey://127.0.0.1:1/0", timedelta(seconds=2.5)
    ).configuration()
    assert configuration.request_timeout == 2500


@pytest.mark.parametrize("url", ["redis://127.0.0.1:6379/0", "http://127.0.0.1", "valkey:///0"])
def test_anything_but_a_valkey_url_is_refused(url: str) -> None:
    with pytest.raises(ValueError):
        ValkeyConnection(url, TIMEOUT)


async def test_a_cache_after_close_is_a_miss_not_an_error() -> None:
    connection = ValkeyConnection("valkey://127.0.0.1:1/0", TIMEOUT)
    await connection.close()
    cache = CacheValkeyImpl(connection, CacheScope.RATE_LIMIT)
    org = new_id()
    await cache.put(org, "k", b"v", timedelta(seconds=30))
    assert await cache.get(org, "k") is None
    assert await cache.increment(org, "n", timedelta(seconds=30)) == (0, timedelta(seconds=30))


async def test_an_unreachable_server_is_a_miss_not_an_error() -> None:
    """No start(): the first command creates the client, as a health probe does."""
    connection = ValkeyConnection("valkey://127.0.0.1:1/0", TIMEOUT)
    try:
        cache = CacheValkeyImpl(connection, CacheScope.NETWORK_RESPONSE)
        assert await cache.get(new_id(), "k") is None
    finally:
        await connection.close()
