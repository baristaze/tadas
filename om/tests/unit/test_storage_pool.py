"""The bounds every role's pool runs under: the per-role knobs fall back to
the shared one the way the role URLs do, the engine is built with the numbers
settings name, and the healthcheck answers within them."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from tadas.om.storage.impl.postgres import StoragePostgresImpl, connect_args, engine_for
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import RolePool, StorageSettings

URL = "postgresql+asyncpg://tadas:tadas@127.0.0.1:55432/tadas"


def pools_of(**overrides: Any) -> Mapping[DatabaseRole, RolePool]:
    return StorageSettings(database_url=URL, **overrides).role_pools()


def test_a_role_pool_falls_back_to_the_shared_bounds() -> None:
    pools = pools_of(
        database_pool_size=9,
        database_pool_size_queue=3,
        database_checkout_timeout_seconds=4.0,
        database_checkout_timeout_seconds_queue=1.5,
        database_statement_timeout_seconds=8.0,
        database_statement_timeout_seconds_activity=30.0,
    )
    assert pools[DatabaseRole.QUEUE] == RolePool(
        size=3, checkout_timeout_seconds=1.5, statement_timeout_seconds=8.0
    )
    assert pools[DatabaseRole.ACTIVITY] == RolePool(
        size=9, checkout_timeout_seconds=4.0, statement_timeout_seconds=30.0
    )
    assert pools[DatabaseRole.CORE] == RolePool(
        size=9, checkout_timeout_seconds=4.0, statement_timeout_seconds=8.0
    )


def test_every_role_carries_a_bound_with_nothing_set() -> None:
    for role, pool in pools_of().items():
        assert pool.size > 0, role
        assert pool.checkout_timeout_seconds > 0, role
        assert pool.statement_timeout_seconds > 0, role


def test_the_worker_can_hold_a_connection_and_a_lease_per_item() -> None:
    # TADAS_WORKER_CAPACITY is 4 and an item may hold a storage connection and
    # a lease renewal at once; the pool the process draws on serves both, with
    # room left for the claim, the sweep, and the relay.
    assert pools_of()[DatabaseRole.QUEUE].size >= 2 * 4


def test_the_statement_deadline_reaches_postgres_on_every_connection() -> None:
    args = connect_args(RolePool(size=1, checkout_timeout_seconds=2.5, statement_timeout_seconds=7))
    assert args["server_settings"] == {"statement_timeout": "7000"}
    assert args["timeout"] == 2.5


def test_the_engine_is_built_with_the_bounds_the_settings_name() -> None:
    bounds = RolePool(size=6, checkout_timeout_seconds=2.5, statement_timeout_seconds=7)
    pool = cast(QueuePool, engine_for(URL, bounds).pool)
    assert pool.size() == 6
    assert pool._max_overflow == 0
    assert pool.timeout() == 2.5


async def test_roles_share_a_pool_only_when_url_and_bounds_agree() -> None:
    shared = RolePool(size=4, checkout_timeout_seconds=1.0, statement_timeout_seconds=2.0)
    urls = dict.fromkeys(DatabaseRole, URL)

    root = StoragePostgresImpl(urls, dict.fromkeys(DatabaseRole, shared), system_urls=urls)
    assert len(root._engines) == 1
    await root.close()

    split = dict.fromkeys(DatabaseRole, shared)
    split[DatabaseRole.QUEUE] = RolePool(
        size=8, checkout_timeout_seconds=1.0, statement_timeout_seconds=2.0
    )
    root = StoragePostgresImpl(urls, split, system_urls=urls)
    assert len(root._engines) == 2
    await root.close()


class HangingEngine:
    """An engine whose connect never returns: a pool with nothing to give."""

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[None]:
        await asyncio.Event().wait()
        yield None

    async def dispose(self) -> None:
        return None


async def test_the_healthcheck_answers_false_within_its_role_bounds() -> None:
    pool = RolePool(size=1, checkout_timeout_seconds=0.05, statement_timeout_seconds=0.05)
    urls = dict.fromkeys(DatabaseRole, URL)
    root = StoragePostgresImpl(urls, dict.fromkeys(DatabaseRole, pool), system_urls=urls)
    await root.close()
    root._engines = {(URL, pool): cast(AsyncEngine, HangingEngine())}

    async with asyncio.timeout(1.0):
        assert await root.healthcheck() is False
