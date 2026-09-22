"""Every role's migrated schema agrees with the ORM metadata, the latest
revision of every role downgrades and upgrades again, the logins are safe to
make twice, and a data migration passes the fence it runs under."""

import pytest
from contracts.event_storage import make_event
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from tadas.om.base import new_id
from tadas.om.events.storage.impl.postgres import EventStoragePostgresImpl
from tadas.om.storage.impl.pg_base import LoginSessions
from tadas.om.storage.migrate import backfill, check, downgrade, ensure_logins_at, head, upgrade
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import MigrationSettings

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("role", list(DatabaseRole))
async def test_orm_and_schema_agree(migrated: dict[DatabaseRole, str], role: DatabaseRole) -> None:
    assert await check(role, migrated[role]) == []


@pytest.mark.parametrize("role", list(DatabaseRole))
async def test_latest_revision_round_trips(
    migrated: dict[DatabaseRole, str], role: DatabaseRole
) -> None:
    if head(role) is None:
        pytest.skip(f"role {role.value} has no migrations yet")
    await downgrade(role, migrated[role], "-1")
    await upgrade(role, migrated[role])
    assert await check(role, migrated[role]) == []


async def test_ensure_logins_runs_again_on_a_migrated_database(
    migration_settings: MigrationSettings, migrated: dict[DatabaseRole, str]
) -> None:
    """The deploy runs it before every migrate, so the second run over a
    database it already shaped changes nothing and fails nothing."""
    settings = migration_settings
    await ensure_logins_at(settings.master_url(), settings.login_passwords())
    for role in DatabaseRole:
        assert await check(role, migrated[role]) == []


async def seed_two_tenants(pg_sessions: LoginSessions) -> None:
    events = EventStoragePostgresImpl(pg_sessions)
    for org in (new_id(), new_id()):
        await events.append_event(org, make_event(org))


def forced(connection: Connection) -> bool:
    return connection.exec_driver_sql(
        "SELECT relforcerowsecurity FROM pg_class WHERE oid = 'activity.events'::regclass"
    ).scalar_one()


COUNT = "SELECT count(*) FROM activity.events"
UPDATE = "UPDATE activity.events SET kind = kind"


async def test_a_backfill_under_the_fence_touches_every_tenant(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """A migration names no tenant, and FORCE binds the migration login that
    owns the table, so a bare UPDATE matches no row and succeeds; its count
    says zero too, and zero equals zero. Seeded with two tenants' rows, the
    backfill counts and touches both, and the fence is back after it."""
    await seed_two_tenants(pg_sessions)
    engine = create_async_engine(migrated[DatabaseRole.ACTIVITY])
    try:
        async with engine.connect() as connection:

            def bare(sync: Connection) -> tuple[int, int]:
                expected = sync.exec_driver_sql(COUNT).scalar_one()
                return expected, sync.exec_driver_sql(UPDATE).rowcount

            assert await connection.run_sync(bare) == (0, 0)
            await connection.rollback()

            def fenced(sync: Connection) -> tuple[int, bool]:
                touched = backfill(sync, DatabaseRole.ACTIVITY, "events", COUNT, UPDATE)
                return touched, forced(sync)

            assert await connection.run_sync(fenced) == (2, True)
            await connection.rollback()
    finally:
        await engine.dispose()


async def test_a_backfill_that_misses_rows_fails_and_keeps_the_fence(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    await seed_two_tenants(pg_sessions)
    engine = create_async_engine(migrated[DatabaseRole.ACTIVITY])
    try:
        async with engine.connect() as connection:
            partial = (
                "UPDATE activity.events SET kind = kind WHERE seq = 1"
                " AND org_id = (SELECT org_id FROM activity.events ORDER BY org_id LIMIT 1)"
            )
            with pytest.raises(RuntimeError, match="touched 1 rows of 2"):
                await connection.run_sync(
                    lambda sync: backfill(sync, DatabaseRole.ACTIVITY, "events", COUNT, partial)
                )
            await connection.rollback()
            assert await connection.run_sync(forced) is True
    finally:
        await engine.dispose()
