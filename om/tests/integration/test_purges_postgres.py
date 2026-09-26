"""The purges, held by a live Postgres: each one's statements are served by an
index, and a row another transaction holds is skipped, not waited on.

The plans are read off the statements the storage impls send, captured as
they go to the driver, so what is explained is the purge itself and not a
copy of it. Each is explained with sequential scans switched off: on a
table this small the planner would read the heap whatever indexes exist,
and the question here is whether an index can serve the statement at all.
A predicate no index serves, such as `done_at < x OR failed_at < x` with no
index on `failed_at`, still plans a sequential scan then.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from contracts.factories import make_session, make_socket_ticket
from contracts.idempotency_storage import make_record
from contracts.slack_storage import make_post
from contracts.task_storage import make_task, seed
from contracts.work_storage import make_item
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from tadas.om.base import EMPTY_UUID, new_id, utcnow
from tadas.om.idempotency.storage.impl.postgres import IdempotencyStoragePostgresImpl
from tadas.om.outbox.storage.impl.postgres import OutboxStoragePostgresImpl
from tadas.om.slack.storage.impl.postgres import SlackStoragePostgresImpl
from tadas.om.storage.impl.pg_base import LoginSessions, set_scope
from tadas.om.storage.impl.postgres import login_sessions
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import MigrationSettings
from tadas.om.tasks.storage.impl.postgres import TasksStoragePostgresImpl
from tadas.om.tenancy.storage.impl.postgres import TenancyStoragePostgresImpl
from tadas.om.work.storage.impl.postgres import WorkStoragePostgresImpl
from tadas.om.work.types.work_item import WorkStatus

pytestmark = pytest.mark.integration

Statement = tuple[str, Any]


@pytest.fixture
async def watched(
    migration_settings: MigrationSettings, migrated: dict[DatabaseRole, str]
) -> AsyncIterator[tuple[LoginSessions, list[AsyncEngine]]]:
    """The sessions the storage roots build, with their engines in hand so a
    case can read the statements that go through them."""
    sessions, engines = login_sessions(
        migration_settings.role_urls(),
        migration_settings.role_pools(),
        system_urls=migration_settings.system_role_urls(),
    )
    yield sessions, list(engines.values())
    for engine in engines.values():
        await engine.dispose()


async def sent(
    engines: list[AsyncEngine], call: Callable[[], Awaitable[object]]
) -> list[Statement]:
    """The statements `call` sends, but for the scope each transaction opens with."""
    captured: list[Statement] = []

    def record(conn: Any, cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if "set_config" not in statement:
            captured.append((statement, parameters))

    for engine in engines:
        event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        await call()
    finally:
        for engine in engines:
            event.remove(engine.sync_engine, "before_cursor_execute", record)
    return captured


async def plan(
    sessions: LoginSessions, role: DatabaseRole, org_id: UUID, statement: Statement
) -> str:
    """The plan of one captured statement under the scope it ran in, with
    sequential scans switched off. EXPLAIN runs nothing."""
    factories = sessions.system if org_id == EMPTY_UUID else sessions
    async with factories[role]() as session:
        await set_scope(session, org_id, None, None)
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        connection = await session.connection()
        sql, parameters = statement
        rows = await connection.exec_driver_sql(f"EXPLAIN {sql}", parameters)
        await session.rollback()
        return "\n".join(row[0] for row in rows)


async def plans(
    watched: tuple[LoginSessions, list[AsyncEngine]],
    role: DatabaseRole,
    org_id: UUID,
    call: Callable[[], Awaitable[object]],
) -> list[str]:
    sessions, engines = watched
    return [await plan(sessions, role, org_id, s) for s in await sent(engines, call)]


def served(found: str, index: str) -> bool:
    return index in found and "Seq Scan" not in found


async def test_the_outbox_purge_is_two_statements_each_on_its_own_index(
    watched: tuple[LoginSessions, list[AsyncEngine]],
) -> None:
    outbox = OutboxStoragePostgresImpl(watched[0])
    done, failed = await plans(
        watched, DatabaseRole.CORE, EMPTY_UUID, lambda: outbox.purge_done(utcnow(), 1000)
    )
    assert served(done, "ix_outbox_rows_done_at_id"), done
    assert served(failed, "ix_outbox_rows_failed_at"), failed


async def test_the_purges_the_new_indexes_serve_read_them(
    watched: tuple[LoginSessions, list[AsyncEngine]],
) -> None:
    sessions = watched[0]
    org = new_id()
    now = utcnow()
    (tasks,) = await plans(
        watched,
        DatabaseRole.CORE,
        org,
        lambda: TasksStoragePostgresImpl(sessions).read_deleted(org, now, 1000),
    )
    assert served(tasks, "ix_tasks_org_id_deleted_at"), tasks
    tenancy = await plans(
        watched,
        DatabaseRole.CORE,
        org,
        lambda: TenancyStoragePostgresImpl(sessions).purge_deleted(org, now, now, 1000),
    )
    assert any(served(p, "ix_sessions_org_id_expires_at") for p in tenancy), tenancy
    assert any(served(p, "ix_socket_tickets_org_id_expires_at") for p in tenancy), tenancy
    (records,) = await plans(
        watched,
        DatabaseRole.CORE,
        org,
        lambda: IdempotencyStoragePostgresImpl(sessions).purge_records(org, now, new_id(), 1000),
    )
    assert served(records, "ix_idempotency_records_org_id_created_at"), records
    slack = await plans(
        watched,
        DatabaseRole.CORE,
        org,
        lambda: SlackStoragePostgresImpl(sessions).purge(org, now, 1000),
    )
    assert served(slack[-1], "ix_slack_posts_org_id_created_at"), slack[-1]
    (work,) = await plans(
        watched,
        DatabaseRole.QUEUE,
        EMPTY_UUID,
        lambda: WorkStoragePostgresImpl(sessions).purge_items(now, 1000),
    )
    assert served(work, "ix_work_items_status_updated_at"), work


async def test_a_purge_skips_a_task_another_transaction_holds(pg_sessions: LoginSessions) -> None:
    """A row locked elsewhere is left for the next call, not waited on: the
    purge takes the rest and returns at once."""
    storage = TasksStoragePostgresImpl(pg_sessions)
    org = new_id()
    cut = utcnow()
    held, free = make_task("held"), make_task("free")
    for task in (held, free):
        await seed(
            storage,
            org,
            task.model_copy(update={"deleted_at": cut - timedelta(days=1), "deleted_by": org}),
        )
    async with pg_sessions[DatabaseRole.CORE]() as holder:
        await set_scope(holder, org, None, None)
        await holder.execute(
            text("SELECT id FROM core.tasks WHERE id = :id FOR UPDATE"), {"id": held.id}
        )
        assert await storage.purge_deleted(org, cut, [held.id, free.id]) == 1
        assert await storage.purge_tenant(org, 10) == 0, "the held one is still held"
        await holder.rollback()
    assert await storage.purge_deleted(org, cut, [held.id, free.id]) == 1
    assert await storage.read_task(org, held.id) is None


async def test_a_cross_tenant_purge_skips_a_row_another_transaction_holds(
    pg_sessions: LoginSessions,
) -> None:
    storage = WorkStoragePostgresImpl(pg_sessions)
    org = new_id()
    settled = {
        "status": WorkStatus.DONE,
        "updated_at": utcnow() - timedelta(days=2),
        "claim_token": None,
        "claimed_by": None,
        "lease_expires_at": None,
    }
    items = [make_item(lane="purges").model_copy(update=settled) for _ in range(3)]
    for item in items:
        await storage.create_item(org, item)
    cut = utcnow() - timedelta(days=1)
    async with pg_sessions.system[DatabaseRole.QUEUE]() as holder:
        await set_scope(holder, EMPTY_UUID, None, None)
        await holder.execute(
            text("SELECT id FROM queue.work_items WHERE id = :id FOR UPDATE"),
            {"id": items[0].id},
        )
        assert await storage.purge_items(cut, 10) == 2
        await holder.rollback()
    assert await storage.purge_items(cut, 10) == 1


async def test_a_session_purge_skips_a_row_another_transaction_holds(
    pg_sessions: LoginSessions,
) -> None:
    storage = TenancyStoragePostgresImpl(pg_sessions)
    org = new_id()
    user = new_id()
    dead = [make_session(new_id(), user, uuid4().hex, ttl=timedelta(days=-2)) for _ in range(2)]
    for session in dead:
        await storage.write_session(org, session)
    await storage.write_socket_ticket(
        org, make_socket_ticket(user, uuid4().hex, ttl=timedelta(days=-2))
    )
    cut = utcnow() - timedelta(days=1)
    async with pg_sessions[DatabaseRole.CORE]() as holder:
        await set_scope(holder, org, None, None)
        await holder.execute(
            text("SELECT id FROM core.sessions WHERE id = :id FOR UPDATE"), {"id": dead[0].id}
        )
        assert await storage.purge_deleted(org, cut, cut, 10) == 2, "a session and the ticket"
        await holder.rollback()
    assert await storage.purge_deleted(org, cut, cut, 10) == 1


async def test_records_and_posts_go_a_batch_at_a_time_over_postgres(
    pg_sessions: LoginSessions,
) -> None:
    """The same batches as the contract suites, over the statements the
    indexes above serve."""
    org = new_id()
    now = utcnow()
    records = IdempotencyStoragePostgresImpl(pg_sessions)
    for i in range(3):
        old = make_record(key=f"old-{i}", created_at=now - timedelta(days=2))
        await records.write_record(org, old.model_copy(update={"status": 201, "body": "{}"}))
    assert await records.purge_records(org, now - timedelta(days=1), new_id(), 2) == 2
    assert await records.purge_records(org, now - timedelta(days=1), new_id(), 2) == 1
    slack = SlackStoragePostgresImpl(pg_sessions)
    for _ in range(3):
        await slack.create_post(org, make_post(new_id()))
    assert await slack.purge(org, now + timedelta(hours=1), 2) == 2
    assert await slack.purge(org, now + timedelta(hours=1), 2) == 1
