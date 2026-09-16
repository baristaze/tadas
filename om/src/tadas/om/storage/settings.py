"""The storage half of every process's settings object: one URL per role,
each defaulting to the shared one."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from tadas.om.storage.roles import DatabaseRole


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TADAS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://tadas:tadas@127.0.0.1:55432/tadas"
    database_url_core: str | None = None
    database_url_activity: str | None = None
    database_url_queue: str | None = None
    database_url_admin: str | None = None

    def role_urls(self) -> dict[DatabaseRole, str]:
        overrides = {
            DatabaseRole.CORE: self.database_url_core,
            DatabaseRole.ACTIVITY: self.database_url_activity,
            DatabaseRole.QUEUE: self.database_url_queue,
            DatabaseRole.ADMIN: self.database_url_admin,
        }
        return {role: overrides[role] or self.database_url for role in DatabaseRole}
