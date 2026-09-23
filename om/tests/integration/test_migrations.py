"""Every role's migrated schema agrees with the ORM metadata, the latest
revision of every role downgrades and upgrades again, the logins are safe to
make twice, a data migration passes the fence it runs under, and the personal
org backfill gives every person one."""

import pytest
from contracts.event_storage import make_event
from contracts.factories import (
    make_identity,
    make_membership,
    make_org,
    make_personal_org,
    make_user,
)
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from tadas.om.base import new_id
from tadas.om.events.storage.impl.postgres import EventStoragePostgresImpl
from tadas.om.opcontext import Role
from tadas.om.storage.impl.pg_base import LoginSessions
from tadas.om.storage.migrate import backfill, check, downgrade, ensure_logins_at, head, upgrade
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import MigrationSettings
from tadas.om.tenancy.rules import MAX_SLUG_LENGTH, SLUG_PATTERN
from tadas.om.tenancy.storage.impl.postgres import TenancyStoragePostgresImpl
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.issued import OrgMembership

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


# The personal org backfill.


BEFORE_BACKFILL = "202609250000"
"""The revision that adds the columns; the one after it gives every existing
person their personal org. The test steps back to here by name, never by a
count: later revisions sit on top of the backfill, the step back takes them
down with it, and the upgrade to the head brings them back."""


async def person_without_a_place(
    storage: TenancyStoragePostgresImpl, email: str, name: str | None
) -> Identity:
    """A person the way the release before the personal org made one: an
    identity, and a team org they own when they have a name."""
    identity = make_identity(email)
    if name is None:
        await storage.write_identity(identity)
        return identity
    org = make_org(name)
    owner = make_user(identity.id, email).model_copy(update={"display_name": name})
    await storage.create_org_with_owner(
        org.id, org, owner, make_membership(owner.id, Role.OWNER), identity
    )
    return identity


def fenced(connection: Connection) -> list[bool]:
    return list(
        connection.exec_driver_sql(
            "SELECT relforcerowsecurity FROM pg_class WHERE oid IN"
            " ('core.orgs'::regclass, 'core.users'::regclass, 'core.memberships'::regclass)"
        ).scalars()
    )


async def test_the_backfill_gives_every_person_one_personal_org(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """People of two tenants and none, one who has a personal org already, and
    a platform identity: the backfill makes one personal org for each person
    who has none, in their name, with their user and the owner membership, and
    none for the platform. A second run finds nobody, and the fence is back."""
    storage = TenancyStoragePostgresImpl(pg_sessions)
    ann = await person_without_a_place(storage, "ann@example.test", "Ann")
    bob = await person_without_a_place(storage, "bob@example.test", "Bob Ó'Brien")
    nameless = await person_without_a_place(storage, "cid@example.test", None)
    platform = await person_without_a_place(storage, "smoke@platform.tadas.invalid", None)
    dee = make_identity("dee@example.test")
    home = make_personal_org(dee.id)
    dee_user = make_user(dee.id, "dee@example.test")
    await storage.create_org_with_owner(
        home.id, home, dee_user, make_membership(dee_user.id, Role.OWNER), dee
    )
    before = await storage.count_orgs()

    await downgrade(DatabaseRole.CORE, migrated[DatabaseRole.CORE], BEFORE_BACKFILL)
    await upgrade(DatabaseRole.CORE, migrated[DatabaseRole.CORE])

    async def personal(identity: Identity) -> list[OrgMembership]:
        places = await storage.read_memberships_by_identity(identity.id, 10)
        return [p for p in places if p.org.personal]

    for identity, org_name, shown in (
        (ann, "Ann", "Ann"),
        (bob, "Bob Ó'Brien", "Bob Ó'Brien"),
        (nameless, "Personal", "cid"),
    ):
        [place] = await personal(identity)
        assert place.org.name == org_name and place.user.display_name == shown
        assert place.role is Role.OWNER and place.org.personal_identity_id == identity.id
        assert SLUG_PATTERN.fullmatch(place.org.slug) and len(place.org.slug) <= MAX_SLUG_LENGTH
        assert place.org.created_by == place.user.id == place.user.created_by
    assert (await personal(bob))[0].org.slug.startswith("bob-")
    assert [p.org.id for p in await personal(dee)] == [home.id]
    assert await storage.read_memberships_by_identity(platform.id, 10) == []
    assert await storage.count_orgs() == before + 3

    # Idempotent: run again, and nobody is left to do.
    await downgrade(DatabaseRole.CORE, migrated[DatabaseRole.CORE], BEFORE_BACKFILL)
    await upgrade(DatabaseRole.CORE, migrated[DatabaseRole.CORE])
    assert await storage.count_orgs() == before + 3
    assert await check(DatabaseRole.CORE, migrated[DatabaseRole.CORE]) == []
    engine = create_async_engine(migrated[DatabaseRole.CORE])
    try:
        async with engine.connect() as connection:
            assert await connection.run_sync(fenced) == [True, True, True]
    finally:
        await engine.dispose()
