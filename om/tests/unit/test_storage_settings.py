"""The local-database guard: a development command refuses a role URL whose
host is not local, and the migration runner refuses before it connects."""

import pytest

from tadas.om.storage import migrate
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import MigrationSettings, StorageSettings

REMOTE = "postgresql+asyncpg://tadas:secret@db.example.internal:5432/tadas"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "postgres", "[::1]"])
def test_a_local_host_passes(host: str) -> None:
    StorageSettings(database_url=f"postgresql+asyncpg://t:t@{host}:5432/t").refuse_remote()


def test_a_remote_host_on_any_role_is_refused() -> None:
    shared = StorageSettings(database_url=REMOTE)
    with pytest.raises(SystemExit, match=r"refusing to touch core at db\.example\.internal"):
        shared.refuse_remote()
    one_role = StorageSettings(database_url_queue=REMOTE)
    with pytest.raises(SystemExit, match="refusing to touch queue"):
        one_role.refuse_remote()


def test_the_migration_runner_refuses_a_remote_database_with_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TADAS_DATABASE_URL", REMOTE)
    for command in (["upgrade", "--all"], ["check", "--all"], ["downgrade", "--all", "--to", "-1"]):
        with pytest.raises(SystemExit, match="refusing to touch"):
            migrate.main([*command, "--local"])


@pytest.mark.parametrize(
    "field",
    [
        "database_pool_size",
        "database_pool_size_queue",
        "database_checkout_timeout_seconds_core",
        "database_statement_timeout_seconds_queue",
    ],
)
def test_a_zero_bound_is_refused_rather_than_read_as_unset(field: str) -> None:
    """A role's zero would fall through to the shared value, and a statement
    deadline of zero means none to Postgres; neither is what was asked for."""
    with pytest.raises(ValueError):
        StorageSettings.model_validate({"_env_file": None, field: 0})


LOCAL = "postgresql+asyncpg://{login}:{login}-pw@127.0.0.1:55432/tadas"


def logins(**overrides: str) -> MigrationSettings:
    values = {
        "database_url": LOCAL.format(login="tadas_runtime"),
        "database_system_url": LOCAL.format(login="tadas_system"),
        "database_migration_url": LOCAL.format(login="tadas_migration"),
        "database_master_url": LOCAL.format(login="tadas"),
        **overrides,
    }
    return MigrationSettings.model_validate({"_env_file": None, **values})


def test_each_login_password_comes_from_its_url() -> None:
    assert logins().login_passwords() == {
        "tadas_migration": "tadas_migration-pw",
        "tadas_runtime": "tadas_runtime-pw",
        "tadas_system": "tadas_system-pw",
    }


def test_a_url_naming_another_login_is_refused() -> None:
    # The policies name the system login, so a URL that names another one
    # would make logins the fence does not know.
    wrong = logins(database_system_url=LOCAL.format(login="someone"))
    with pytest.raises(SystemExit, match="names the login 'someone'"):
        wrong.login_passwords()


def test_the_migrations_run_under_the_migration_login() -> None:
    urls = logins().migration_role_urls()
    assert set(urls.values()) == {LOCAL.format(login="tadas_migration")}


def test_a_role_on_its_own_database_keeps_its_database_under_every_login() -> None:
    moved = logins(database_url_queue="postgresql+asyncpg://tadas_runtime:r@db-q:5432/q")
    assert moved.migration_role_urls()[DatabaseRole.QUEUE] == (
        "postgresql+asyncpg://tadas_migration:tadas_migration-pw@db-q:5432/q"
    )
    assert moved.system_role_urls()[DatabaseRole.QUEUE] == (
        "postgresql+asyncpg://tadas_system:tadas_system-pw@db-q:5432/q"
    )


def test_ensure_logins_needs_the_master() -> None:
    with pytest.raises(SystemExit, match="TADAS_DATABASE_MASTER_URL"):
        MigrationSettings.model_validate({"_env_file": None}).master_url()


def test_a_remote_master_is_refused_with_local() -> None:
    with pytest.raises(SystemExit, match="refusing to touch the master"):
        logins(database_master_url=REMOTE).refuse_remote()
