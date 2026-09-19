"""The storage half of every process's settings object: one URL per role,
each defaulting to the shared one."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from tadas.om.storage.roles import DatabaseRole

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "postgres"})
"""Where a development seed may write; the compose service name included."""


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TADAS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://tadas:tadas@127.0.0.1:55432/tadas"
    database_url_core: str | None = None
    database_url_activity: str | None = None
    database_url_queue: str | None = None
    database_url_admin: str | None = None

    def refuse_remote(self) -> None:
        """For a development command (the seed, `make migrate`, the integration
        tests): refuses a role URL whose host is not local, so a stray `.env`
        never points a local command at a shared database."""
        for role, url in self.role_urls().items():
            host = make_url(url).host
            if host not in LOCAL_HOSTS:
                raise SystemExit(
                    f"refusing to touch {role.value} at {host}: TADAS_DATABASE_URL must be local"
                )

    def role_urls(self) -> dict[DatabaseRole, str]:
        overrides = {
            DatabaseRole.CORE: self.database_url_core,
            DatabaseRole.ACTIVITY: self.database_url_activity,
            DatabaseRole.QUEUE: self.database_url_queue,
            DatabaseRole.ADMIN: self.database_url_admin,
        }
        return {role: overrides[role] or self.database_url for role in DatabaseRole}
