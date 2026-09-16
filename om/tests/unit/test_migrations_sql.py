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
    assert role_metadata(DatabaseRole.ACTIVITY).tables == {}
