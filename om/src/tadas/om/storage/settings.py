"""The storage half of every process's settings object: one URL per role and
one set of pool bounds per role, each defaulting to the shared one."""

from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from tadas.om.storage.roles import DatabaseRole

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "postgres"})
"""Where a development seed may write; the compose service name included."""


@dataclass(frozen=True)
class RolePool:
    """The bounds one role's pool runs under: how many connections it opens, how
    long a checkout waits before it fails, and the deadline every statement on
    it carries. Both bounds are in seconds."""

    size: int
    checkout_timeout_seconds: float
    statement_timeout_seconds: float


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TADAS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://tadas:tadas@127.0.0.1:55432/tadas"
    database_url_core: str | None = None
    database_url_activity: str | None = None
    database_url_queue: str | None = None
    database_url_admin: str | None = None

    # Every role's pool declares its size and the bound on waiting for a
    # connection, and every statement it runs carries a deadline, so a role
    # under load fails the call that could not get a connection instead of
    # queueing without end, and a query that hangs costs one call and not a
    # connection held until it dies. The size is the whole pool: the storage
    # root opens no connection past it. The shared value serves every role;
    # a role with its own load profile takes its own.
    database_pool_size: int = 12
    database_pool_size_core: int | None = None
    database_pool_size_activity: int | None = None
    database_pool_size_queue: int | None = None
    database_pool_size_admin: int | None = None

    database_checkout_timeout_seconds: float = 5.0
    database_checkout_timeout_seconds_core: float | None = None
    database_checkout_timeout_seconds_activity: float | None = None
    database_checkout_timeout_seconds_queue: float | None = None
    database_checkout_timeout_seconds_admin: float | None = None

    database_statement_timeout_seconds: float = 10.0
    database_statement_timeout_seconds_core: float | None = None
    database_statement_timeout_seconds_activity: float | None = None
    database_statement_timeout_seconds_queue: float | None = None
    database_statement_timeout_seconds_admin: float | None = None

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

    def role_pools(self) -> dict[DatabaseRole, RolePool]:
        """The bounds of every role's pool, each knob defaulting to its shared
        value the way a role URL does. Nothing here is optional: a role whose
        settings name no override still carries a size, a checkout bound, and a
        statement deadline, so no engine is built on a library default."""
        sizes = {
            DatabaseRole.CORE: self.database_pool_size_core,
            DatabaseRole.ACTIVITY: self.database_pool_size_activity,
            DatabaseRole.QUEUE: self.database_pool_size_queue,
            DatabaseRole.ADMIN: self.database_pool_size_admin,
        }
        checkouts = {
            DatabaseRole.CORE: self.database_checkout_timeout_seconds_core,
            DatabaseRole.ACTIVITY: self.database_checkout_timeout_seconds_activity,
            DatabaseRole.QUEUE: self.database_checkout_timeout_seconds_queue,
            DatabaseRole.ADMIN: self.database_checkout_timeout_seconds_admin,
        }
        statements = {
            DatabaseRole.CORE: self.database_statement_timeout_seconds_core,
            DatabaseRole.ACTIVITY: self.database_statement_timeout_seconds_activity,
            DatabaseRole.QUEUE: self.database_statement_timeout_seconds_queue,
            DatabaseRole.ADMIN: self.database_statement_timeout_seconds_admin,
        }
        return {
            role: RolePool(
                size=sizes[role] or self.database_pool_size,
                checkout_timeout_seconds=(
                    checkouts[role] or self.database_checkout_timeout_seconds
                ),
                statement_timeout_seconds=(
                    statements[role] or self.database_statement_timeout_seconds
                ),
            )
            for role in DatabaseRole
        }
