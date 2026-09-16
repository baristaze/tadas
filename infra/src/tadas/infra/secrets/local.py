import asyncio
import stat
from collections.abc import Mapping
from pathlib import Path

from tadas.infra.secrets import SecretNotFound, SecretsFileNotPrivate, SecretsInterface


class SecretsLocalImpl(SecretsInterface):
    """The overrides the settings object collected at boot (TADAS_SECRET_<NAME>
    in the environment, keyed by NAME), then an owner-only file of NAME=value
    lines. Writes go to the file. Nothing here reads the environment."""

    def __init__(self, file: Path | None, overrides: Mapping[str, str] | None = None) -> None:
        self._file = file
        self._overrides = dict(overrides or {})

    async def get(self, name: str) -> str:
        value = self._overrides.get(name.upper())
        if value is not None:
            return value
        entries = await asyncio.to_thread(self._read_file)
        if name in entries:
            return entries[name]
        raise SecretNotFound(name, "local")

    async def has(self, name: str) -> bool:
        if name.upper() in self._overrides:
            return True
        return name in await asyncio.to_thread(self._read_file)

    async def put(self, name: str, value: str) -> None:
        def write() -> None:
            entries = self._read_file()
            entries[name] = value
            self._write_file(entries)

        await asyncio.to_thread(write)

    async def delete(self, name: str) -> None:
        def write() -> None:
            entries = self._read_file()
            entries.pop(name, None)
            self._write_file(entries)

        await asyncio.to_thread(write)

    def describe(self) -> str:
        return f"secrets=local({self._file or 'env only'})"

    def _read_file(self) -> dict[str, str]:
        if self._file is None or not self._file.exists():
            return {}
        mode = stat.S_IMODE(self._file.stat().st_mode)
        if mode & 0o077:
            raise SecretsFileNotPrivate(f"{self._file} must be owner-only (mode 600), is {mode:o}")
        entries: dict[str, str] = {}
        for line in self._file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            entries[key.strip()] = value.strip()
        return entries

    def _write_file(self, entries: dict[str, str]) -> None:
        if self._file is None:
            raise SecretsFileNotPrivate("no secrets file configured; set TADAS_SECRETS_FILE")
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.touch(mode=0o600, exist_ok=True)
        self._file.chmod(0o600)
        self._file.write_text("".join(f"{k}={v}\n" for k, v in sorted(entries.items())))

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
