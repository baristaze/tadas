"""Every role's migrated schema agrees with the ORM metadata, the latest
revision of every role downgrades and upgrades again, the logins are safe to
make twice, a data migration passes the fence it runs under, the personal
org backfill gives every person one, and the due date backfill gives every
task with a due time its date."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from contracts.event_storage import make_event
from contracts.factories import (
    make_identity,
    make_membership,
    make_org,
    make_personal_org,
    make_user,
)
from contracts.task_storage import make_task
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine

from tadas.om.base import new_id
from tadas.om.events.storage.impl.postgres import EventStoragePostgresImpl
from tadas.om.opcontext import Role
from tadas.om.storage.impl.pg_base import LoginSessions, set_scope
from tadas.om.storage.migrate import backfill, check, downgrade, ensure_logins_at, head, upgrade
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import MigrationSettings
from tadas.om.tasks.storage.impl.postgres import TasksStoragePostgresImpl
from tadas.om.tasks.types.task import Task
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
        await events.append_events(org, [make_event(org)])


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
    # The rest of the chain again, so the suite goes on at the head.
    await upgrade(DatabaseRole.CORE, migrated[DatabaseRole.CORE])
    assert await check(DatabaseRole.CORE, migrated[DatabaseRole.CORE]) == []
    engine = create_async_engine(migrated[DatabaseRole.CORE])
    try:
        async with engine.connect() as connection:
            assert await connection.run_sync(fenced) == [True, True, True]
    finally:
        await engine.dispose()


# The due date backfill.


BEFORE_DUE_DATE_BACKFILL = "202609261600"
"""The revision that adds `tasks.due_on`; the one after it fills it from the
due time. Stepped back to by name, as above."""


def raw(connection: Connection, sql: str) -> list[tuple[object, ...]]:
    """A statement over every tenant's tasks: the fence lifted for it and put
    back, in the caller's transaction, as a migration does."""
    connection.exec_driver_sql("ALTER TABLE core.tasks NO FORCE ROW LEVEL SECURITY")
    result = connection.exec_driver_sql(sql)
    rows = [tuple(row) for row in result] if result.returns_rows else []
    connection.exec_driver_sql("ALTER TABLE core.tasks FORCE ROW LEVEL SECURITY")
    return rows


async def on_core(url: str, sql: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            return await connection.run_sync(lambda sync: raw(sync, sql))
    finally:
        await engine.dispose()


async def test_the_due_date_backfill_takes_the_utc_date_in_every_tenant(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """Tasks of two tenants, as the release before wrote them: a due time and
    no due date. The backfill gives each the UTC date of its due time and
    leaves a task without one alone. The due time leaves the table later
    (202609290000), so the downgrade brings it back empty and then gives the
    release before a due time on each due date, and the fence is back after
    both."""
    core = migrated[DatabaseRole.CORE]
    storage = TasksStoragePostgresImpl(pg_sessions)
    ann_org, zoe_org = new_id(), new_id()
    late = make_task("late in Lima")
    plain = make_task("no due time")
    other = make_task("another tenant's")
    for org, task in ((ann_org, late), (ann_org, plain), (zoe_org, other)):
        assert await storage.create_task(org, task, ())

    await downgrade(DatabaseRole.CORE, core, BEFORE_DUE_DATE_BACKFILL)
    await on_core(
        core,
        "UPDATE core.tasks SET due_on = NULL, remind_at = CASE title"
        " WHEN 'late in Lima' THEN timestamptz '2030-09-30 23:30:00-05'"
        " WHEN 'another tenant''s' THEN timestamptz '2030-10-02 08:00:00+00' END",
    )
    await upgrade(DatabaseRole.CORE, core)

    async def due(task: Task, org: UUID) -> date | None:
        stored = await storage.read_task(org, task.id)
        assert stored is not None
        return stored.due_on

    assert await due(late, ann_org) == date(2030, 10, 1), "the UTC date of the due time"
    assert await due(other, zoe_org) == date(2030, 10, 2), "the other tenant's too"
    assert await due(plain, ann_org) is None

    # A due date moved at the head is the one the downgrade reads.
    moved = late.model_copy(update={"due_on": date(2030, 12, 24), "version": late.version + 1})
    await storage.update_task(ann_org, moved, late.version, ())

    # A downgrade restores a due time on every due date: nine in the morning
    # of it, UTC, since the old column comes back empty.
    await downgrade(DatabaseRole.CORE, core, BEFORE_DUE_DATE_BACKFILL)
    rows = await on_core(core, "SELECT title, remind_at FROM core.tasks")
    restored = {title: at for title, at in rows}
    assert restored == {
        "late in Lima": datetime(2030, 12, 24, 9, tzinfo=UTC),
        "no due time": None,
        "another tenant's": datetime(2030, 10, 2, 9, tzinfo=UTC),
    }

    await upgrade(DatabaseRole.CORE, core)
    assert await check(DatabaseRole.CORE, core) == []
    engine = create_async_engine(core)
    try:
        async with engine.connect() as connection:
            assert await connection.run_sync(
                lambda sync: sync.exec_driver_sql(
                    "SELECT relforcerowsecurity FROM pg_class WHERE oid = 'core.tasks'::regclass"
                ).scalar_one()
            )
    finally:
        await engine.dispose()


# The rank, filled from the position and kept for the release before.


BEFORE_RANK = "202610030000"
"""The revision before the one that adds `tasks.rank`."""

POSITIONS = (0.1, 1e-05, -2.5, 3.0000000000000004, 12345678.9, 0.30000000000000004)
"""Floats whose text is not their first fifteen digits, and one that no
decimal of fifteen digits tells from its neighbour."""


async def as_the_release_before(
    sessions: LoginSessions, org: UUID, sql: str, **values: object
) -> None:
    """A statement the release before sends, under the runtime login and the
    tenant's scope: it names the position and never the rank."""
    async with sessions[DatabaseRole.CORE]() as session:
        await set_scope(session, org, None, None)
        await session.execute(text(sql), {"org": org, **values})
        await session.commit()


async def test_the_rank_is_the_position_digit_for_digit_and_follows_the_release_before(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    core = migrated[DatabaseRole.CORE]
    storage = TasksStoragePostgresImpl(pg_sessions)
    ann, zoe = new_id(), new_id()
    tasks = [make_task(f"p{index}", rank=position) for index, position in enumerate(POSITIONS)]
    for index, task in enumerate(tasks):
        placed = task.model_copy(update={"position": POSITIONS[index]})
        assert await storage.create_task(ann if index % 2 else zoe, placed, ())

    # The fill: every existing row, every tenant, its rank the float's text.
    await downgrade(DatabaseRole.CORE, core, BEFORE_RANK)
    await upgrade(DatabaseRole.CORE, core)
    rows = await on_core(core, "SELECT title, position, rank FROM core.tasks ORDER BY title")
    assert [(position, rank) for _, position, rank in rows] == [
        (position, Decimal(repr(position))) for position in POSITIONS
    ]

    # The release before creates a task: no rank, and the trigger gives it
    # the one its position names, which this release reads it at.
    created = new_id()
    await as_the_release_before(
        pg_sessions,
        ann,
        "INSERT INTO core.tasks (id, org_id, created_at, updated_at, created_by, updated_by,"
        " title, notes, status, position, version)"
        " VALUES (:id, :org, now(), now(), :id, :id, 'before', '', 'open', -7.25, 1)",
        id=created,
    )
    stored = await storage.read_task(ann, created)
    assert stored is not None and stored.rank == Decimal("-7.25")

    # The release before moves it by the position alone, and edits a title.
    await as_the_release_before(
        pg_sessions,
        ann,
        "UPDATE core.tasks SET position = 0.15, version = 2 WHERE id = :id",
        id=created,
    )
    await as_the_release_before(
        pg_sessions, ann, "UPDATE core.tasks SET title = 'renamed' WHERE id = :id", id=created
    )
    stored = await storage.read_task(ann, created)
    assert stored is not None and (stored.rank, stored.title) == (Decimal("0.15"), "renamed")
    places = await storage.read_open_places(ann, None, None, limit=10)
    assert [rank for rank, _ in places] == sorted(
        [Decimal("0.15"), *(Decimal(repr(p)) for i, p in enumerate(POSITIONS) if i % 2)]
    )

    # This release writes the rank itself; the position beside it is the
    # rank's float, and the trigger leaves the rank as written.
    exact = Decimal("0.1500000000000000000000001")
    moved = stored.model_copy(
        update={"rank": exact, "position": float(exact), "version": stored.version + 1}
    )
    await storage.update_task(ann, moved, stored.version, ())
    stored = await storage.read_task(ann, created)
    assert stored is not None and stored.rank == exact and stored.position == 0.15

    # Downgraded, the release before reads the position this release kept.
    await downgrade(DatabaseRole.CORE, core, BEFORE_RANK)
    rows = await on_core(core, f"SELECT position FROM core.tasks WHERE id = '{created}'")
    assert rows == [(0.15,)]
    await upgrade(DatabaseRole.CORE, core)
    assert await check(DatabaseRole.CORE, core) == []
