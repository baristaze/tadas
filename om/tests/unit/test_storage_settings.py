"""The local-database guard: a development command refuses a role URL whose
host is not local, and the migration runner refuses before it connects."""

import pytest

from tadas.om.storage import migrate
from tadas.om.storage.settings import StorageSettings

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
