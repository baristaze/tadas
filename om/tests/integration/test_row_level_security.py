"""The second fence, read off the migrated database.

`make migrate-check` compares tables, columns, and indexes; a policy is
invisible to it, so what the database holds is asserted here. The contract
suites in this directory are the other half: they run the same cases over
Postgres with the policies live and stay green, which is the business layer
relying on nothing of the fence.
"""

import pytest
from contracts.event_storage import make_event
from contracts.idempotency_storage import make_record
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tadas.om.base import new_id
from tadas.om.events.storage.impl.postgres import EventStoragePostgresImpl
from tadas.om.idempotency.storage.impl.postgres import IdempotencyStoragePostgresImpl
from tadas.om.idempotency.storage.tables.idempotency_records import IdempotencyRecords
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole, role_for
from tadas.om.storage.scopes import POLICY_NAME, TABLE_SCOPES, ScopeKind, scope_for

pytestmark = pytest.mark.integration

Sessions = dict[DatabaseRole, SessionFactory]


async def test_the_login_is_no_superuser_and_cannot_bypass_rls(pg_sessions: Sessions) -> None:
    """The test that makes the fence real and not a claim. A superuser walks
    past every policy, and so does a role with BYPASSRLS; on either, every
    assertion below would pass against a database that fences nothing."""
    for role in DatabaseRole:
        async with pg_sessions[role]() as session:
            found = (
                await session.execute(
                    text(
                        "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles"
                        " WHERE rolname = current_user"
                    )
                )
            ).one()
            assert not found.rolsuper, f"{found.rolname} is a superuser"
            assert not found.rolbypassrls, f"{found.rolname} carries BYPASSRLS"


@pytest.mark.parametrize("table_name", sorted(TABLE_SCOPES))
async def test_every_table_holds_the_policy_its_scope_declares(
    pg_sessions: Sessions, table_name: str
) -> None:
    role = role_for(table_name)
    scope = scope_for(table_name)
    fenced = scope.kind is not ScopeKind.SYSTEM
    async with pg_sessions[role]() as session:
        flags = (
            await session.execute(
                text(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c"
                    " JOIN pg_namespace n ON n.oid = c.relnamespace"
                    " WHERE n.nspname = :schema AND c.relname = :table"
                ),
                {"schema": role.value, "table": table_name},
            )
        ).one()
        assert flags.relrowsecurity is fenced, f"{table_name}: row security {flags.relrowsecurity}"
        assert flags.relforcerowsecurity is fenced, (
            f"{table_name}: force {flags.relforcerowsecurity}"
        )
        policies = (
            await session.execute(
                text(
                    "SELECT policyname, cmd, qual, with_check FROM pg_policies"
                    " WHERE schemaname = :schema AND tablename = :table"
                ),
                {"schema": role.value, "table": table_name},
            )
        ).all()
    if not fenced:
        assert policies == [], f"{table_name} is system-scoped and carries {policies}"
        return
    assert len(policies) == 1, f"{table_name} carries {len(policies)} policies"
    policy = policies[0]
    assert policy.policyname == POLICY_NAME
    assert policy.cmd == "ALL"
    for expression in (policy.qual, policy.with_check):
        assert expression is not None
        assert "org_id" in expression, f"{table_name}: no tenant in {expression}"
        assert "'00000000-0000-0000-0000-000000000000'" in expression, (
            f"{table_name}: the system scope is not spelled in the policy"
        )
        narrowed = scope.person_column is not None and scope.person_column in expression
        assert narrowed == (scope.kind is ScopeKind.BOTH), (
            f"{table_name} is {scope.kind.value} and the policy says otherwise: {expression}"
        )


async def test_a_transaction_with_no_scope_reads_nothing_and_writes_refuse(
    pg_sessions: Sessions,
) -> None:
    """Fail closed. A transaction that names no tenant is not a transaction
    that sees every tenant; the setting reads as NULL, every comparison to
    NULL is false, and the policy holds. The read going silently empty is the
    accepted price, and the write is refused outright."""
    org = new_id()
    events = EventStoragePostgresImpl(pg_sessions)
    appended = await events.append_event(org, make_event(org))
    assert await events.read_head(org) == 1

    async with pg_sessions[DatabaseRole.ACTIVITY]() as session:
        assert (await session.execute(text("SELECT id FROM activity.events"))).all() == []
        cursors = text("SELECT org_id FROM activity.event_cursors")
        assert (await session.execute(cursors)).all() == []
        with pytest.raises(DBAPIError) as refused:
            await session.execute(
                text("INSERT INTO activity.event_cursors (org_id, head) VALUES (:org, 1)"),
                {"org": org},
            )
        assert "row-level security" in str(refused.value)

    # The row is there; it is the transaction that could not see it.
    assert await events.read_after(org, 0, 10) == [appended]


async def test_a_narrowed_transaction_sees_only_its_person(pg_sessions: Sessions) -> None:
    """A `both`-scoped table narrows to one person when the transaction names
    one. The markers are per (tenant, user, key), so a transaction opened for
    one user reads that user's rows and no other's, with no predicate of its
    own in the statement."""
    org = new_id()
    markers = IdempotencyStoragePostgresImpl(pg_sessions)
    mine, theirs = make_record(key="mine"), make_record(key="theirs")
    await markers.write_record(org, mine)
    await markers.write_record(org, theirs)

    read_all = text("SELECT key FROM core.idempotency_records ORDER BY key")
    async with markers._session_for(IdempotencyRecords, org) as session:
        assert [row.key for row in await session.execute(read_all)] == ["mine", "theirs"]
    async with markers._session_for(IdempotencyRecords, org, mine.user_id) as session:
        assert [row.key for row in await session.execute(read_all)] == ["mine"]
    async with markers._session_for(IdempotencyRecords, org, theirs.user_id) as session:
        assert [row.key for row in await session.execute(read_all)] == ["theirs"]
