from pathlib import Path

import pytest

from tadas.infra.impl.settings import InfraSettings
from tadas.infra.secrets import SecretNotFound, SecretsFileNotPrivate
from tadas.infra.secrets.local import SecretsLocalImpl


async def test_boot_time_overrides_win_over_the_file(tmp_path: Path) -> None:
    secrets = SecretsLocalImpl(tmp_path / "secrets.env")
    await secrets.put("db_password", "from-file")
    assert await secrets.get("db_password") == "from-file"
    overridden = SecretsLocalImpl(tmp_path / "secrets.env", {"DB_PASSWORD": "from-env"})
    assert await overridden.get("db_password") == "from-env"
    assert await overridden.has("db_password")


def test_settings_collect_the_overrides_once_at_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TADAS_SECRET_DB_PASSWORD", "from-env")
    monkeypatch.setenv("TADAS_SECRET_", "ignored: no name")
    settings = InfraSettings.model_validate({"environment": "test"})
    assert settings.secret_overrides == {"DB_PASSWORD": "from-env"}
    monkeypatch.setenv("TADAS_SECRET_LATER", "set after boot")
    assert "LATER" not in settings.secret_overrides
    assert "secret_overrides" not in settings.model_dump()


def test_the_overrides_come_from_dot_env_too_and_the_environment_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.env.example` documents TADAS_SECRET_<NAME> as a `.env` knob, so it has
    to work like one. Pydantic's dotenv source cannot supply these — one key
    per secret is not a declared field — so the file is read here; the process
    environment still wins, the way it does for every other setting."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "TADAS_SECRET_DB_PASSWORD=from-the-file  # with a comment\n"
        "TADAS_SECRET_API_TOKEN=only-in-the-file\n"
    )
    monkeypatch.setenv("TADAS_SECRET_DB_PASSWORD", "from-the-environment")
    settings = InfraSettings.model_validate({"environment": "test"})
    assert settings.secret_overrides == {
        "DB_PASSWORD": "from-the-environment",
        "API_TOKEN": "only-in-the-file",
    }


async def test_missing_secret_names_the_store_not_a_value(tmp_path: Path) -> None:
    secrets = SecretsLocalImpl(tmp_path / "secrets.env")
    assert not await secrets.has("nothing")
    with pytest.raises(SecretNotFound) as raised:
        await secrets.get("nothing")
    assert "local" in raised.value.message


async def test_file_must_be_owner_only(tmp_path: Path) -> None:
    file = tmp_path / "secrets.env"
    file.write_text("token=abc\n")
    file.chmod(0o644)
    with pytest.raises(SecretsFileNotPrivate):
        await SecretsLocalImpl(file).get("token")
    file.chmod(0o600)
    assert await SecretsLocalImpl(file).get("token") == "abc"


async def test_delete_removes_from_the_file(tmp_path: Path) -> None:
    secrets = SecretsLocalImpl(tmp_path / "secrets.env")
    await secrets.put("a", "1")
    await secrets.put("b", "2")
    await secrets.delete("a")
    assert not await secrets.has("a")
    assert await secrets.get("b") == "2"
