"""The pool bounds, held by a live Postgres.

The unit suite proves the engine is built with the numbers the settings name.
These cases prove the numbers do what they say on a real connection: every
contract case over Postgres runs under the settings' own deadline, a
statement past its deadline is cancelled by the database, and a checkout past
the pool waits its bound and fails. The last two set small bounds of their
own, so each answers in a fraction of a second; the defaults are not changed
by anything here.
"""

import time
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from tadas.om.storage.impl.pg_base import LoginSessions
from tadas.om.storage.impl.postgres import login_sessions
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import MigrationSettings, RolePool

pytestmark = pytest.mark.integration

QUERY_CANCELED = "57014"
"""Postgres's SQLSTATE for a statement cancelled by `statement_timeout`."""


@pytest.fixture
async def tight_sessions(
    migration_settings: MigrationSettings, migrated: dict[DatabaseRole, str]
) -> AsyncIterator[LoginSessions]:
    """The runtime login's sessions under one connection, a short checkout
    bound, and a short deadline."""
    pool = RolePool(size=1, checkout_timeout_seconds=0.3, statement_timeout_seconds=0.3)
    sessions, engines = login_sessions(
        migration_settings.role_urls(),
        dict.fromkeys(DatabaseRole, pool),
        system_urls=migration_settings.system_role_urls(),
    )
    yield sessions
    for engine in engines.values():
        await engine.dispose()


async def test_the_contract_suites_run_under_the_settings_deadline(
    pg_sessions: LoginSessions, migration_settings: MigrationSettings
) -> None:
    """Every login the contract cases use carries the deadline the settings
    name, which a bare engine would not: Postgres's own default is none."""
    pools = migration_settings.role_pools()
    for factories in (pg_sessions, pg_sessions.system):
        for role in DatabaseRole:
            async with factories[role]() as session:
                shown = (await session.execute(text("SHOW statement_timeout"))).scalar_one()
            expected = round(pools[role].statement_timeout_seconds * 1000)
            assert shown in {f"{expected}ms", f"{expected // 1000}s"}, (role, shown)


async def test_a_statement_past_its_deadline_is_cancelled_by_postgres(
    tight_sessions: LoginSessions,
) -> None:
    started = time.monotonic()
    with pytest.raises(DBAPIError) as refused:
        async with tight_sessions[DatabaseRole.CORE]() as session:
            await session.execute(text("SELECT pg_sleep(5)"))
    assert getattr(refused.value.orig, "sqlstate", None) == QUERY_CANCELED
    assert time.monotonic() - started < 2.0


async def test_a_checkout_past_the_pool_waits_its_bound_and_fails(
    tight_sessions: LoginSessions,
) -> None:
    """One connection held, a second asked for: the pool opens none past its
    size, so the second waits the checkout bound and fails instead of queueing
    without end."""
    factory = tight_sessions[DatabaseRole.CORE]
    async with factory() as holder:
        await holder.execute(text("SELECT 1"))
        started = time.monotonic()
        with pytest.raises(PoolTimeoutError):
            async with factory() as second:
                await second.execute(text("SELECT 1"))
        waited = time.monotonic() - started
    assert 0.3 <= waited < 2.0
