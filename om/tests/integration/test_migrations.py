"""Every role's migrated schema agrees with the ORM metadata, the latest
revision of every role downgrades and upgrades again, the logins are safe to
make twice, a migration behind a held lock gives up within its bound, and a
data migration passes the fence it runs under and fails when it misses rows.
What Tadas's own schema keeps holds too: a task's rank and position follow
each other, and the database folds an address as the process does."""

import asyncio
import time
from decimal import Decimal
from uuid import UUID

import pytest
from contracts.event_storage import make_event
from contracts.factories import make_identity
from contracts.task_storage import bump, make_task
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine

from tadas.om.base import new_id
from tadas.om.events.storage.impl.postgres import EventStoragePostgresImpl
from tadas.om.exceptions import UniqueKeyTaken
from tadas.om.storage.impl.pg_base import LoginSessions, set_scope
from tadas.om.storage.migrate import (
    RUN_AGAIN,
    VERSION_TABLE,
    backfill,
    check,
    downgrade,
    ensure_logins_at,
    head,
    main,
    upgrade,
)
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import MigrationSettings
from tadas.om.tasks.storage.impl.postgres import TasksStoragePostgresImpl
from tadas.om.tenancy.rules import email_digest
from tadas.om.tenancy.storage.impl.postgres import TenancyStoragePostgresImpl

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


async def version_of_core(url: str) -> list[str]:
    """The revision core's version table holds: none while the role is a
    step down from its one revision."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(text(f"SELECT version_num FROM core.{VERSION_TABLE}"))
            return [str(version) for (version,) in rows]
    finally:
        await engine.dispose()


async def test_a_migration_behind_a_held_lock_gives_up_within_its_bound(
    migrated: dict[DatabaseRole, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A transaction holds core's version table, which every run of core's
    chain reads first, so it stands for a lock on any table a migration
    touches. With the bound at one second, `migrate upgrade` gives up after
    that second, applies nothing, and exits RUN_AGAIN, which the deploy's
    pre-rollout task runs again on. Once the transaction ends, the same
    command applies the revision. Without the bound, the run waits for as
    long as the transaction stays open.

    A step down from the head empties the role, so the upgrade back runs
    whatever the case found, and the suite goes on at the head."""
    core = migrated[DatabaseRole.CORE]
    await downgrade(DatabaseRole.CORE, core, "-1")
    try:
        before = await version_of_core(core)
        monkeypatch.setenv("TADAS_DATABASE_MIGRATION_LOCK_TIMEOUT_SECONDS", "1")
        holder = create_async_engine(core)
        try:
            async with holder.begin() as held:
                await held.execute(
                    text(f"LOCK TABLE core.{VERSION_TABLE} IN ACCESS EXCLUSIVE MODE")
                )
                started = time.monotonic()
                code = await asyncio.to_thread(main, ["upgrade", "--role", "core"])
                waited = time.monotonic() - started
        finally:
            await holder.dispose()
        assert code == RUN_AGAIN
        # The second of waiting, and what it costs to open a connection and
        # read the chain around it.
        assert 1.0 <= waited < 3.0
        assert "core: a lock was not granted within 1 s" in capsys.readouterr().err
        assert await version_of_core(core) == before
    finally:
        applied = await asyncio.to_thread(main, ["upgrade", "--role", "core"])
    assert applied == 0
    assert await check(DatabaseRole.CORE, core) == []


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


# A task's rank and its position, kept in step by the database.


def raw(connection: Connection, sql: str) -> list[tuple[object, ...]]:
    """A statement over every tenant's tasks: the fence lifted for it and put
    back, in the caller's transaction, as a migration does."""
    connection.exec_driver_sql("ALTER TABLE core.tasks NO FORCE ROW LEVEL SECURITY")
    result = connection.exec_driver_sql(sql)
    rows = [tuple(row) for row in result] if result.returns_rows else []
    connection.exec_driver_sql("ALTER TABLE core.tasks FORCE ROW LEVEL SECURITY")
    return rows


async def on_core(url: str, sql: str) -> list[tuple[object, ...]]:
    """One statement on the core role, as the migration login, with the
    tasks' fence lifted for it (`raw`)."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            return await connection.run_sync(lambda sync: raw(sync, sql))
    finally:
        await engine.dispose()


POSITIONS = (0.1, 1e-05, -2.5, 3.0000000000000004, 12345678.9, 0.30000000000000004)
"""Floats whose text is not their first fifteen digits, and one that no
decimal of fifteen digits tells from its neighbour."""

LONG = Decimal("0.1500000000000000000000001")
"""A rank whose float, 0.15, holds only its first digits."""


async def as_a_writer_of_columns(
    sessions: LoginSessions, org: UUID, sql: str, **values: object
) -> None:
    """A statement that names its columns itself, under the runtime login and
    the tenant's scope."""
    async with sessions[DatabaseRole.CORE]() as session:
        await set_scope(session, org, None, None)
        await session.execute(text(sql), {"org": org, **values})
        await session.commit()


async def places(core: str) -> dict[str, tuple[object, ...]]:
    """Each task's rank and position, by title, as the database holds them."""
    rows = await on_core(core, "SELECT title, rank, position FROM core.tasks")
    return {str(title): (rank, position) for title, rank, position in rows}


async def test_a_row_written_by_its_position_takes_the_rank_the_position_names(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """A writer that names the position and no rank: the trigger gives the
    row the rank its position names, digit for digit, on the insert and on a
    move by the position alone, and leaves the rank on any other write."""
    core = migrated[DatabaseRole.CORE]
    storage = TasksStoragePostgresImpl(pg_sessions)
    ann, zoe = new_id(), new_id()
    insert = (
        "INSERT INTO core.tasks (id, org_id, created_at, updated_at, created_by, updated_by,"
        " title, notes, status, position, version)"
        " VALUES (:id, :org, now(), now(), :id, :id, :title, '', 'open', :position, 1)"
    )

    # Every float's text is its rank, in every tenant.
    for index, position in enumerate(POSITIONS):
        await as_a_writer_of_columns(
            pg_sessions,
            ann if index % 2 else zoe,
            insert,
            id=new_id(),
            title=f"p{index}",
            position=position,
        )
    rows = await on_core(core, "SELECT title, position, rank FROM core.tasks ORDER BY title")
    assert [(position, rank) for _, position, rank in rows] == [
        (position, Decimal(repr(position))) for position in POSITIONS
    ]

    # A task made with no rank reads at the one its position names.
    created = new_id()
    await as_a_writer_of_columns(
        pg_sessions, ann, insert, id=created, title="by position", position=-7.25
    )
    stored = await storage.read_task(ann, created)
    assert stored is not None and stored.rank == Decimal("-7.25")

    # A move by the position alone, then an edit of the title.
    await as_a_writer_of_columns(
        pg_sessions,
        ann,
        "UPDATE core.tasks SET position = 0.15, version = 2 WHERE id = :id",
        id=created,
    )
    await as_a_writer_of_columns(
        pg_sessions, ann, "UPDATE core.tasks SET title = 'renamed' WHERE id = :id", id=created
    )
    stored = await storage.read_task(ann, created)
    assert stored is not None and (stored.rank, stored.title) == (Decimal("0.15"), "renamed")
    open_places = await storage.read_open_places(ann, None, None, limit=10)
    assert [rank for rank, _ in open_places] == sorted(
        [Decimal("0.15"), *(Decimal(repr(p)) for i, p in enumerate(POSITIONS) if i % 2)]
    )

    # The storage writes the rank alone; the position takes the rank's
    # float, and the rank stays as written.
    moved = stored.model_copy(update={"rank": LONG, "version": stored.version + 1})
    await storage.update_task(ann, moved, stored.version, ())
    stored = await storage.read_task(ann, created)
    assert stored is not None and stored.rank == LONG
    rows = await on_core(core, f"SELECT position FROM core.tasks WHERE id = '{created}'")
    assert rows == [(0.15,)]
    assert await check(DatabaseRole.CORE, core) == []


async def test_the_position_is_the_ranks_float_on_every_row_written(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """The storage names no position. A writer that names the rank and the
    position, its float, writes over the storage's rows, and the storage
    over that writer's. Every row reads at the rank written."""
    core = migrated[DatabaseRole.CORE]
    storage = TasksStoragePostgresImpl(pg_sessions)
    org = new_id()

    # The storage creates a task and moves it. It writes the rank alone,
    # and the position takes the rank's float each time.
    mine = make_task("mine", rank="-2.5")
    assert await storage.create_task(org, mine, ())
    assert (await places(core))["mine"] == (Decimal("-2.5"), -2.5)
    mine = await bump(storage, org, mine, rank=LONG)
    assert (await places(core))["mine"] == (LONG, 0.15)

    # A writer that names both creates a task and moves it: both stay as
    # written.
    theirs = new_id()
    await as_a_writer_of_columns(
        pg_sessions,
        org,
        "INSERT INTO core.tasks (id, org_id, created_at, updated_at, created_by, updated_by,"
        " title, notes, status, rank, position, version)"
        " VALUES (:id, :org, now(), now(), :id, :id, 'theirs', '', 'open', -3, -3.0, 1)",
        id=theirs,
    )
    await as_a_writer_of_columns(
        pg_sessions,
        org,
        "UPDATE core.tasks SET rank = :rank, position = :position, version = 2 WHERE id = :id",
        id=theirs,
        rank=LONG + Decimal("1e-25"),
        position=float(LONG),
    )
    assert (await places(core))["theirs"] == (LONG + Decimal("1e-25"), 0.15)

    # That writer moves the storage's task to the place it holds: it names
    # the same rank and that rank's float, which the row holds, so the rank
    # keeps every digit. Then it edits the title, naming both as read.
    for sql in (
        "UPDATE core.tasks SET rank = :rank, position = :position, version = 3 WHERE id = :id",
        "UPDATE core.tasks SET title = 'mine, edited', rank = :rank, position = :position,"
        " version = 4 WHERE id = :id",
    ):
        await as_a_writer_of_columns(
            pg_sessions, org, sql, id=mine.id, rank=LONG, position=float(LONG)
        )
    assert (await places(core))["mine, edited"] == (LONG, 0.15)

    # The storage reads both at their ranks: every digit counts, though the
    # two floats tie.
    assert await storage.read_open_places(org, None, None, limit=10) == [
        (LONG, mine.id),
        (LONG + Decimal("1e-25"), theirs),
    ]
    assert await check(DatabaseRole.CORE, core) == []


# An address, folded by the database as the process folds it.


async def test_any_spelling_of_an_address_finds_its_identity_and_a_second_meets_the_index(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """The identity's digest is computed from the address folded to lower
    case. Any spelling finds the identity, and a writer that does not fold
    meets the unique index with a second spelling instead of making a second
    person."""
    storage = TenancyStoragePostgresImpl(pg_sessions)
    tail = new_id().hex[:8]
    dee = make_identity(f"dee-{tail}@example.test")
    await storage.write_identity(dee)

    for spelled in (f"DEE-{tail}@EXAMPLE.TEST", f"dee-{tail}@example.test"):
        assert await storage.read_identity_by_email_digest(email_digest(spelled)) == dee
    with pytest.raises(UniqueKeyTaken):
        await storage.write_identity(make_identity(f"Dee-{tail}@example.test"))
    assert await check(DatabaseRole.CORE, migrated[DatabaseRole.CORE]) == []
