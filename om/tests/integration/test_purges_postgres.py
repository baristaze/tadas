"""The purges and the sweep's requeue of expired leases, held by a live
Postgres: each one's statements are served by an index, and a row another
transaction holds is skipped, not waited on. Every namespace's purge past its
retention runs across tenants in the system scope, each statement on an index
that leads with the retention column; the purge of one tenant past its own
retention reads that tenant's rows by an index that org_id leads.

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
from contracts.event_storage import append_one, make_event
from contracts.event_storage import drained as drained_events
from contracts.factories import make_session, make_socket_ticket
from contracts.idempotency_storage import drained as drained_records
from contracts.idempotency_storage import make_record
from contracts.slack_storage import drained as drained_slack
from contracts.slack_storage import make_post, posted_at
from contracts.task_storage import make_task, seed
from contracts.tenancy_storage import before
from contracts.tenancy_storage import drained as drained_tenancy
from contracts.work_storage import make_item
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tadas.om.base import EMPTY_UUID, new_id, utcnow
from tadas.om.billing.storage.impl.postgres import BillingStoragePostgresImpl
from tadas.om.events.storage.impl.postgres import EventStoragePostgresImpl
from tadas.om.idempotency.storage.impl.postgres import IdempotencyStoragePostgresImpl
from tadas.om.idempotency.types.attempt import lease_bound
from tadas.om.media.storage.impl.postgres import MediaStoragePostgresImpl
from tadas.om.orchestrations.storage.impl.postgres import OrchestrationsStoragePostgresImpl
from tadas.om.outbox.storage.impl.postgres import OutboxStoragePostgresImpl
from tadas.om.slack.storage.impl.postgres import SlackStoragePostgresImpl
from tadas.om.storage.impl.pg_base import LoginSessions, set_scope
from tadas.om.storage.impl.postgres import login_sessions
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import MigrationSettings
from tadas.om.tasks.storage.impl.postgres import TasksStoragePostgresImpl
from tadas.om.tenancy.storage.impl.postgres import TenancyStoragePostgresImpl
from tadas.om.work.storage.impl.postgres import WorkStoragePostgresImpl
from tadas.om.work.types.work_item import WorkKind, WorkStatus

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
    """The statements `call` sends, but for the scope and the plan-cache
    setting a transaction opens with."""
    captured: list[Statement] = []

    def record(conn: Any, cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if "set_config" not in statement and "plan_cache_mode" not in statement:
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


async def settled_and_leased(sessions: LoginSessions, owner_url: str) -> None:
    """A queue of one tenant: settled items, most of them changed after the
    cut the case reads with, so the cut is what picks a batch, and a few
    live leases. Then ANALYZE under the owner, which the statistics need."""
    org = new_id()
    async with sessions[DatabaseRole.QUEUE]() as session:
        await set_scope(session, org, None, None)
        await session.execute(
            text(
                "INSERT INTO queue.work_items (id, org_id, created_at, updated_at, created_by,"
                " updated_by, kind, target_id, idempotency_key, request_id, payload, lane,"
                " status, available_at, lease_expires_at, attempts, max_attempts)"
                " SELECT gen_random_uuid(), :org, now(),"
                " now() + (2900 - g) * interval '20 minutes', :org, :org, 'NOOP',"
                " gen_random_uuid(), gen_random_uuid(), gen_random_uuid(),"
                " '{}', 'default', CASE WHEN g % 50 = 0 THEN 'claimed' ELSE 'done' END, now(),"
                " CASE WHEN g % 50 = 0 THEN now() + interval '1 minute' END, 1, 5"
                " FROM generate_series(1, 3000) g"
            ),
            {"org": org},
        )
        await session.commit()
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("ANALYZE queue.work_items"))
    finally:
        await engine.dispose()


ANCIENT = timedelta(days=36500)
"""How far back a case's cut stands: no row of this database is behind it, so
a statement captured with it deletes nothing, and a case's own rows behind it
are the case's."""


async def test_every_purge_across_tenants_reads_an_index_led_by_its_retention(
    watched: tuple[LoginSessions, list[AsyncEngine]],
) -> None:
    """Each statement of each namespace's purge past its retention, as the
    sweep sends it once a pass for every tenant, in the system scope."""
    sessions = watched[0]
    cut = utcnow() - ANCIENT
    system = EMPTY_UUID

    async def across(role: DatabaseRole, call: Callable[[], Awaitable[object]]) -> list[str]:
        return await plans(watched, role, system, call)

    (tasks,) = await across(
        DatabaseRole.CORE, lambda: TasksStoragePostgresImpl(sessions).read_deleted(cut, 1000)
    )
    assert served(tasks, "ix_tasks_deleted_at"), tasks
    (files,) = await across(
        DatabaseRole.CORE,
        lambda: MediaStoragePostgresImpl(sessions).read_purgeable(cut, cut, 1000),
    )
    assert served(files, "ix_files_deleted_at"), files
    assert served(files, "ix_files_created_at_pending"), files
    users, memberships, keys, tenancy_sessions, tickets, invitations = await across(
        DatabaseRole.CORE,
        lambda: TenancyStoragePostgresImpl(sessions).purge_deleted(cut, cut, 1000),
    )
    assert served(users, "ix_users_deleted_at"), users
    assert served(memberships, "ix_memberships_deleted_at"), memberships
    assert served(keys, "ix_api_keys_deleted_at") and "ix_api_keys_expires_at" in keys, keys
    assert served(tenancy_sessions, "ix_sessions_expires_at"), tenancy_sessions
    assert served(tickets, "ix_socket_tickets_expires_at"), tickets
    assert served(invitations, "ix_invitations_updated_at"), invitations
    assert "ix_invitations_expires_at" in invitations, invitations
    (records,) = await across(
        DatabaseRole.CORE,
        lambda: IdempotencyStoragePostgresImpl(sessions).purge_records(cut, new_id(), 1000),
    )
    assert served(records, "ix_idempotency_records_created_at"), records
    assert "ix_idempotency_records_attempt_id" in records, records
    (trim,) = await across(
        DatabaseRole.ACTIVITY, lambda: EventStoragePostgresImpl(sessions).trim(cut, 1000)
    )
    assert served(trim, "ix_events_produced_at"), trim
    assert "uq_events_org_id_seq" in trim and "pk_event_cursors" in trim, trim
    (deliveries,) = await across(
        DatabaseRole.CORE,
        lambda: BillingStoragePostgresImpl(sessions).purge_deliveries(cut, 1000),
    )
    assert served(deliveries, "ix_billing_deliveries_created_at"), deliveries
    installations, states, posts = await across(
        DatabaseRole.CORE, lambda: SlackStoragePostgresImpl(sessions).purge(cut, 1000)
    )
    assert served(installations, "ix_slack_installations_deleted_at"), installations
    assert served(states, "ix_slack_install_states_expires_at"), states
    assert "ix_slack_install_states_redeemed_at" in states, states
    assert served(posts, "ix_slack_posts_created_at"), posts
    (settled,) = await across(
        DatabaseRole.CORE,
        lambda: OrchestrationsStoragePostgresImpl(sessions).purge_settled(cut, 1000),
    )
    assert served(settled, "ix_orchestrations_status_updated_at"), settled


async def test_the_queue_purge_reads_its_index(
    watched: tuple[LoginSessions, list[AsyncEngine]], migrated: dict[DatabaseRole, str]
) -> None:
    # Two indexes of the queue lead with the status, and on an empty table
    # they cost the same; the planner's choice is only a real one over rows
    # and their statistics, so the queue gets both before its plan is read.
    sessions = watched[0]
    await settled_and_leased(sessions, migrated[DatabaseRole.QUEUE])
    (work,) = await plans(
        watched,
        DatabaseRole.QUEUE,
        EMPTY_UUID,
        lambda: WorkStoragePostgresImpl(sessions).purge_items(utcnow(), 1000),
    )
    assert served(work, "ix_work_items_status_updated_at"), work


async def test_a_purge_skips_a_task_another_transaction_holds(pg_sessions: LoginSessions) -> None:
    """A row locked elsewhere is left for the next call, not waited on: the
    purge takes the rest and returns at once."""
    storage = TasksStoragePostgresImpl(pg_sessions)
    org = new_id()
    cut = utcnow() - ANCIENT
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
        assert await storage.purge_deleted(cut, [held.id, free.id]) == 1
        assert await storage.purge_tenant(org, 10) == 0, "the held one is still held"
        await holder.rollback()
    assert await storage.purge_deleted(cut, [held.id, free.id]) == 1
    assert await storage.read_task(org, held.id) is None


async def test_the_trim_skips_a_stream_an_append_holds_and_trims_the_others(
    pg_sessions: LoginSessions,
) -> None:
    """An append holds its tenant's cursor row to its commit. The trim takes
    every other tenant's run in the meantime and leaves that one for its next
    call, never waiting on it; the floor of each tenant moves with its own."""
    storage = EventStoragePostgresImpl(pg_sessions)
    now = await drained_events(storage)
    busy, idle = new_id(), new_id()
    for org in (busy, idle):
        for _ in range(2):
            await append_one(storage, org, make_event(org, produced_at=now - timedelta(days=100)))
    before = now - timedelta(days=90)
    async with pg_sessions[DatabaseRole.ACTIVITY]() as holder:
        await set_scope(holder, busy, None, None)
        await holder.execute(
            text("SELECT head FROM activity.event_cursors WHERE org_id = :org FOR UPDATE"),
            {"org": busy},
        )
        assert await storage.trim(before, 1000) == 2, "the idle tenant's, not the busy one's"
        await holder.rollback()
    assert await storage.read_floor(idle) == 2
    assert await storage.read_floor(busy) == 0
    assert await storage.trim(before, 1000) == 2
    assert await storage.read_floor(busy) == 2
    assert await storage.read_after(busy, 0, 10) == []


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


async def test_the_requeue_of_expired_leases_reads_its_index_across_tenants(
    watched: tuple[LoginSessions, list[AsyncEngine]],
) -> None:
    (requeue,) = await plans(
        watched,
        DatabaseRole.QUEUE,
        EMPTY_UUID,
        lambda: WorkStoragePostgresImpl(watched[0]).requeue_stale(utcnow(), timedelta(0), 100),
    )
    assert served(requeue, "ix_work_items_status_lease_expires_at"), requeue


async def test_the_requeue_skips_an_item_another_transaction_holds(
    pg_sessions: LoginSessions,
) -> None:
    """An item a worker is renewing or settling is locked by that write; the
    requeue takes the others and leaves it for the next call, never waits."""
    storage = WorkStoragePostgresImpl(pg_sessions)
    while await storage.requeue_stale(utcnow(), timedelta(0), 1000):
        pass  # the expired leases the cases before this one left
    lane = f"requeue-{new_id().hex[-12:]}"
    org_a, org_b = new_id(), new_id()
    for org in (org_a, org_b, org_b):
        await storage.create_item(org, make_item(lane=lane))
    claimed = []
    for _ in range(3):
        found = await storage.claim_next(lane, [WorkKind.NOOP], "w1", timedelta(seconds=-1))
        assert found is not None
        claimed.append(found)
    held_org, held = claimed[0]
    async with pg_sessions.system[DatabaseRole.QUEUE]() as holder:
        await set_scope(holder, EMPTY_UUID, None, None)
        await holder.execute(
            text("SELECT id FROM queue.work_items WHERE id = :id FOR UPDATE"), {"id": held.id}
        )
        moved = await storage.requeue_stale(utcnow(), timedelta(0), 10)
        assert sorted(item.id for _, item in moved) == sorted(i.id for _, i in claimed[1:])
        await holder.rollback()
    assert [
        (org, item.id) for org, item in await storage.requeue_stale(utcnow(), timedelta(0), 10)
    ] == [(held_org, held.id)]


async def test_a_session_purge_skips_a_row_another_transaction_holds(
    pg_sessions: LoginSessions,
) -> None:
    storage = TenancyStoragePostgresImpl(pg_sessions)
    cut = await drained_tenancy(storage)
    org = new_id()
    user = new_id()
    gone = before(cut, timedelta(days=1))
    dead = [make_session(new_id(), user, uuid4().hex, ttl=gone) for _ in range(2)]
    for session in dead:
        await storage.write_session(org, session)
    await storage.write_socket_ticket(org, make_socket_ticket(user, uuid4().hex, ttl=gone))
    async with pg_sessions[DatabaseRole.CORE]() as holder:
        await set_scope(holder, org, None, None)
        await holder.execute(
            text("SELECT id FROM core.sessions WHERE id = :id FOR UPDATE"), {"id": dead[0].id}
        )
        assert await storage.purge_deleted(cut, cut, 10) == 2, "a session and the ticket"
        await holder.rollback()
    assert await storage.purge_deleted(cut, cut, 10) == 1


async def test_records_and_posts_go_a_batch_at_a_time_over_postgres(
    pg_sessions: LoginSessions,
) -> None:
    """The same batches as the contract suites, over the statements the
    indexes above serve."""
    org = new_id()
    records = IdempotencyStoragePostgresImpl(pg_sessions)
    now = await drained_records(records)
    for i in range(3):
        old = make_record(key=f"old-{i}", created_at=now - timedelta(days=2))
        await records.write_record(org, old.model_copy(update={"status": 201, "body": "{}"}))
    cut, attempts_before = now - timedelta(days=1), lease_bound(now - timedelta(minutes=20))
    assert await records.purge_records(cut, attempts_before, 2) == 2
    assert await records.purge_records(cut, attempts_before, 2) == 1
    slack = SlackStoragePostgresImpl(pg_sessions)
    then = await drained_slack(slack)
    for _ in range(3):
        await slack.create_post(org, posted_at(make_post(new_id()), then))
    assert await slack.purge(then + timedelta(hours=1), 2) == 2
    assert await slack.purge(then + timedelta(hours=1), 2) == 1
