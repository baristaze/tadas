"""Fixtures shared by the OM test suites. The integration fixtures refuse
any database that is not a local address."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.migrate import upgrade_all
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
