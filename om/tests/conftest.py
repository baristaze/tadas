"""Fixtures shared by the OM test suites. The integration fixtures refuse
any database that is not a local address."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.migrate import VERSION_TABLE, upgrade_all
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import LOCAL_HOSTS, StorageSettings


@pytest.fixture(scope="session")
def role_urls() -> dict[DatabaseRole, str]:
    urls = StorageSettings().role_urls()
    for url in urls.values():
        host = make_url(url).host
        assert host in LOCAL_HOSTS, f"refusing to run integration tests against {host}"
    return urls


@pytest.fixture(scope="session")
def migrated(role_urls: dict[DatabaseRole, str]) -> dict[DatabaseRole, str]:
    asyncio.run(upgrade_all(role_urls))
    return role_urls


@pytest.fixture
async def pg_sessions(
    migrated: dict[DatabaseRole, str],
) -> AsyncIterator[dict[DatabaseRole, SessionFactory]]:
    engines: dict[str, AsyncEngine] = {}
    sessions: dict[DatabaseRole, SessionFactory] = {}
    for role in DatabaseRole:
        url = migrated[role]
        engines.setdefault(url, create_async_engine(url))
        sessions[role] = async_sessionmaker(engines[url], expire_on_commit=False)
    yield sessions
    for engine in engines.values():
        await engine.dispose()


@pytest.fixture(autouse=True)
async def empty_schemas(request: pytest.FixtureRequest) -> None:
    """Every integration test starts on empty tables.

    These suites are the contract cases, and each one is written as if it owns
    the tables: a memory impl hands each test a fresh dict, while Postgres
    keeps what the last run left in one local database. Rows that outlive a
    test do not fail it honestly, they fail it for the wrong reason, and the
    failures move with the order the tests ran in: a `claim_pending(100)` that
    never reaches the row the case just wrote, a downgrade that cannot put a
    full unique index back over rows a soft delete left beside each other.
    Truncating is the whole isolation this suite needs, since no case depends
    on what another wrote, and it is what makes `make test-integration`
    re-runnable without `make reset` in front of it.
    """
    if request.node.get_closest_marker("integration") is None:
        return
    urls: dict[DatabaseRole, str] = request.getfixturevalue("migrated")
    for url in dict.fromkeys(urls.values()):
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                schemas = ", ".join(f"'{role.value}'" for role in DatabaseRole)
                # Every table but each role's migration bookkeeping, which
                # says where the schema stands and is not this suite's to
                # clear.
                rows = await connection.execute(
                    text(
                        "SELECT table_schema, table_name FROM information_schema.tables"
                        f" WHERE table_schema IN ({schemas}) AND table_type = 'BASE TABLE'"
                        " AND table_name <> :version_table"
                    ),
                    {"version_table": VERSION_TABLE},
                )
                tables = [f'{schema}."{name}"' for schema, name in rows]
                if tables:
                    await connection.execute(
                        text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
                    )
        finally:
            await engine.dispose()
