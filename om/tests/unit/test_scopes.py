"""Every table declares one tenancy scope, the scope agrees with the table's
mixins and columns, and the migration chain carries the policy the scope
declares. The policy itself is read off the migrated database by
`om/tests/integration/test_row_level_security.py`; this file is what the fast
gate can say without one."""

import importlib
import pkgutil
import re

import pytest

import tadas.om
from tadas.om.storage.migrate import MIGRATIONS_DIR, role_metadata
from tadas.om.storage.roles import TABLE_ROLES, DatabaseRole, role_for
from tadas.om.storage.scopes import (
    POLICY_NAME,
    TABLE_SCOPES,
    ScopeKind,
    TableScope,
    scope_for,
)
from tadas.om.storage.tables.base import Base, GlobalIdentifiableMixin


def import_every_table_module() -> None:
    for module in pkgutil.walk_packages(tadas.om.__path__, prefix="tadas.om."):
        if ".storage.tables." in module.name:
            importlib.import_module(module.name)


def table_classes() -> dict[str, type]:
    import_every_table_module()
    found: dict[str, type] = {}
    for mapper in Base.registry.mappers:
        table_name = getattr(mapper.class_, "__tablename__", None)
        if table_name is not None:
            found[table_name] = mapper.class_
    return found


def test_every_mapped_table_declares_a_scope_and_nothing_extra() -> None:
    import_every_table_module()
    mapped = {name.split(".")[-1] for name in Base.metadata.tables}
    assert mapped, "no tables were imported"
    assert mapped <= set(TABLE_SCOPES), f"no scope for {sorted(mapped - set(TABLE_SCOPES))}"
    assert set(TABLE_SCOPES) <= mapped, f"a scope for nothing: {sorted(set(TABLE_SCOPES) - mapped)}"
    assert set(TABLE_SCOPES) == set(TABLE_ROLES), "the role map and the scope map disagree"


def test_an_unmapped_table_is_refused() -> None:
    with pytest.raises(LookupError):
        scope_for("not_a_table")


def test_a_scope_declares_the_column_its_kind_needs() -> None:
    with pytest.raises(ValueError):
        TableScope(ScopeKind.BOTH)
    with pytest.raises(ValueError):
        TableScope(ScopeKind.BOTH, person_column="user_id", identity_column="identity_id")
    with pytest.raises(ValueError):
        TableScope(ScopeKind.IDENTITY)
    with pytest.raises(ValueError):
        TableScope(ScopeKind.IDENTITY, person_column="user_id", identity_column="identity_id")
    with pytest.raises(ValueError):
        TableScope(ScopeKind.ORG, person_column="user_id")


def test_a_person_is_narrowed_on_the_setting_that_names_it() -> None:
    """A row that names its user narrows on `app.user_id`; a row whose person
    is the identity behind it narrows on `app.identity_id`. The two settings
    carry different ids, so a column compared with the wrong one never
    matches and a narrowed read comes back empty."""
    assert scope_for("users").narrowing == ("identity_id", "app.identity_id")
    assert scope_for("memberships").narrowing == ("user_id", "app.user_id")
    assert scope_for("tasks").narrowing is None


def test_a_global_table_is_the_system_scope_and_nothing_else_is() -> None:
    """`GlobalIdentifiableMixin` is the table that carries no `org_id`, so it
    is exactly the table with no tenant to fence."""
    for name, table_class in table_classes().items():
        global_table = issubclass(table_class, GlobalIdentifiableMixin)
        system = scope_for(name).kind is ScopeKind.SYSTEM
        assert global_table == system, f"{name}: global {global_table}, system {system}"


def test_a_tenant_scope_carries_org_id_and_its_declared_person_column() -> None:
    import_every_table_module()
    for table in Base.metadata.tables.values():
        scope = scope_for(table.name)
        columns = set(table.columns.keys())
        if scope.kind in (ScopeKind.ORG, ScopeKind.BOTH):
            assert "org_id" in columns, f"{table.name} is {scope.kind.value} without org_id"
        if scope.person_column is not None:
            assert scope.person_column in columns, (
                f"{table.name} declares the person column {scope.person_column}, which it lacks"
            )
        if scope.identity_column is not None:
            assert scope.identity_column in columns


def chain(role: DatabaseRole) -> str:
    return "\n".join(
        path.read_text() for path in sorted((MIGRATIONS_DIR / "sql" / role.value).glob("*.up.sql"))
    )


def policy_in(sql: str, qualified: str) -> str | None:
    """The policy a table carries at the end of the chain: the last statement
    that creates or alters it, since a later migration may narrow it anew."""
    statements = re.findall(
        rf"(?:CREATE|ALTER) POLICY {POLICY_NAME} ON {re.escape(qualified)}\b[^;]*;", sql
    )
    return statements[-1] if statements else None


@pytest.mark.parametrize("table_name", sorted(TABLE_SCOPES))
def test_the_chain_carries_the_policy_the_scope_declares(table_name: str) -> None:
    """A table added without a policy fails here, in the fast gate, and not
    only on the migrated database. `make migrate-check` compares tables,
    columns, and indexes; a policy is invisible to it, so the chain is read as
    text and the live database is read by the integration suite."""
    role = role_for(table_name)
    scope = scope_for(table_name)
    qualified = f"{role.value}.{table_name}"
    sql = chain(role)
    enabled = f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY" in sql
    forced = f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY" in sql
    policy = f"CREATE POLICY {POLICY_NAME} ON {qualified}" in sql
    if scope.kind is ScopeKind.SYSTEM:
        assert not (enabled or forced or policy), f"{table_name} is system-scoped and fenced"
        return
    assert enabled and forced, f"{table_name} has no row-level security in the chain"
    assert policy, f"{table_name} has no {POLICY_NAME} policy in the chain"
    latest = policy_in(sql, qualified)
    assert latest is not None
    settings = set(re.findall(r"current_setting\('(app\.\w+)'", latest))
    if scope.narrowing is None:
        assert settings == {"app.org_id"}, f"{table_name} is narrowed on {settings}"
        return
    column, setting = scope.narrowing
    person = f"{column} = NULLIF(current_setting('{setting}', true), '')::uuid"
    assert latest.count(person) == 2, f"{table_name} is not narrowed on {column} by {setting}"
    assert settings == {"app.org_id", setting}, f"{table_name} reads {settings}"


@pytest.mark.parametrize("role", list(DatabaseRole))
def test_the_system_scope_clause_is_spelled_in_every_policy(role: DatabaseRole) -> None:
    """The one deliberate bypass is written into each policy rather than
    granted somewhere else, so `grep` finds every place it holds."""
    sql = chain(role)
    fenced = [
        name
        for name in role_metadata(role).tables
        if scope_for(name.split(".")[-1]).kind is not ScopeKind.SYSTEM
    ]
    policies = sql.count(f"CREATE POLICY {POLICY_NAME} ON ")
    assert policies == len(fenced), f"{role.value}: {policies} policies for {len(fenced)} tables"
    # Twice per policy: `USING` and `WITH CHECK` carry the same expression.
    empty_uuid = "'00000000-0000-0000-0000-000000000000'"
    for name in fenced:
        latest = policy_in(sql, name)
        assert latest is not None, f"{name} has no policy"
        spelled = latest.count(f"current_setting('app.org_id', true) = {empty_uuid}")
        assert spelled == 2, f"{name}: the system scope is spelled {spelled} times"
