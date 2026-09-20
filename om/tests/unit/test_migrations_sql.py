"""The migration files obey the role rules without a database."""

import pytest

from tadas.om.storage.migrate import (
    MIGRATIONS_DIR,
    check_role_of_sql,
    head,
    role_metadata,
    split_statements,
)
from tadas.om.storage.roles import DatabaseRole


def test_every_sql_file_names_only_its_own_role() -> None:
    sql_files = list((MIGRATIONS_DIR / "sql").rglob("*.sql"))
    assert sql_files
    for path in sql_files:
        check_role_of_sql(DatabaseRole(path.parent.name), path.read_text())


def test_a_file_naming_another_role_is_refused() -> None:
    with pytest.raises(RuntimeError):
        check_role_of_sql(DatabaseRole.CORE, "CREATE TABLE queue.work_items (id uuid)")
    with pytest.raises(LookupError):
        check_role_of_sql(DatabaseRole.CORE, "CREATE TABLE core.unknown_table (id uuid)")
    check_role_of_sql(DatabaseRole.QUEUE, "DROP INDEX queue.ix_work_items_org_id")
    check_role_of_sql(DatabaseRole.QUEUE, "ALTER INDEX queue.ix_work_items_a RENAME TO ix_b")
    with pytest.raises(RuntimeError):
        check_role_of_sql(DatabaseRole.CORE, "DROP INDEX queue.ix_work_items_org_id")


def test_split_statements_drops_comments_and_blanks() -> None:
    sql = (
        "-- header\nCREATE TABLE core.orgs (id uuid);\n\n"
        "-- more\nCREATE INDEX ix ON core.orgs (id);\n"
    )
    assert split_statements(sql) == [
        "CREATE TABLE core.orgs (id uuid)",
        "CREATE INDEX ix ON core.orgs (id)",
    ]


@pytest.mark.parametrize("role", list(DatabaseRole))
def test_each_role_has_at_most_one_head_and_stamped_wrappers(role: DatabaseRole) -> None:
    versions = MIGRATIONS_DIR / "versions" / role.value
    wrappers = sorted(versions.glob("*.py")) if versions.is_dir() else []
    if not wrappers:
        assert head(role) is None
        return
    assert head(role) == wrappers[-1].stem.split("_", 1)[0]
    for wrapper in wrappers:
        stamp = wrapper.stem.split("_", 1)[0]
        assert len(stamp) == 12 and stamp.isdigit(), wrapper.name
        assert f'revision = "{stamp}"' in wrapper.read_text()
        for suffix in (".up.sql", ".down.sql"):
            assert (MIGRATIONS_DIR / "sql" / role.value / f"{wrapper.stem}{suffix}").is_file()


def test_role_metadata_holds_only_that_role() -> None:
    core = role_metadata(DatabaseRole.CORE)
    assert {t.name for t in core.tables.values()} >= {"orgs", "identities", "users"}
    assert all(t.schema == "core" for t in core.tables.values())
    assert {t.name for t in role_metadata(DatabaseRole.QUEUE).tables.values()} == {"work_items"}
    assert {t.name for t in role_metadata(DatabaseRole.ACTIVITY).tables.values()} == {
        "events",
        "event_cursors",
    }


SWEEP_INDEXES = {
    "users": "ix_users_org_id_deleted_at",
    "memberships": "ix_memberships_org_id_deleted_at",
}
"""The index the per-tenant purge needs on each soft-deletable table whose
only other org_id index is partial."""


@pytest.mark.parametrize(("table", "name"), sorted(SWEEP_INDEXES.items()))
def test_the_purge_of_a_tenant_has_an_index_the_orm_and_the_chain_agree_on(
    table: str, name: str
) -> None:
    """The sweep reads `org_id = X AND deleted_at < Y` every 30 seconds per
    tenant, and `org_id = X` alone under a deleted one. Both target the rows a
    partial unique index `WHERE deleted_at IS NULL` leaves out, so each table
    carries a plain (org_id, deleted_at) index. `make migrate-check` compares
    the ORM metadata with the migrated schema, so both say it."""
    orm = role_metadata(DatabaseRole.CORE).tables[f"core.{table}"]
    index = next((i for i in orm.indexes if i.name == name), None)
    assert index is not None, f"{table} declares no {name}"
    assert [c.name for c in index.columns] == ["org_id", "deleted_at"]
    assert not index.unique
    assert index.dialect_kwargs.get("postgresql_where") is None, "the dead rows are the point"
    chain = "\n".join(
        path.read_text() for path in (MIGRATIONS_DIR / "sql" / "core").glob("*.up.sql")
    )
    assert f"CREATE INDEX {name} ON core.{table} (org_id, deleted_at)" in chain
