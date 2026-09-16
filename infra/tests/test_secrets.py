from pathlib import Path

import pytest

from tadas.infra.secrets import SecretNotFound, SecretsFileNotPrivate
from tadas.infra.secrets.local import SecretsLocalImpl


async def test_environment_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = SecretsLocalImpl(tmp_path / "secrets.env")
    await secrets.put("db_password", "from-file")
    assert await secrets.get("db_password") == "from-file"
    monkeypatch.setenv("TADAS_SECRET_DB_PASSWORD", "from-env")
    assert await secrets.get("db_password") == "from-env"


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
