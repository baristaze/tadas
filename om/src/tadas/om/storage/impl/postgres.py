"""The relational storage root: one engine and pool per distinct role URL and
its bounds, every namespace impl constructed here."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.storage.impl.postgres import EventStoragePostgresImpl
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.storage.impl.postgres import IdempotencyStoragePostgresImpl
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.storage.impl.postgres import OutboxStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.root import StorageInterface
from tadas.om.storage.settings import RolePool, StorageSettings
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.impl.postgres import TasksStoragePostgresImpl
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.postgres import TenancyStoragePostgresImpl
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.storage.impl.postgres import WorkStoragePostgresImpl


def connect_args(pool: RolePool) -> dict[str, Any]:
    """What every connection of a pool is opened with. `statement_timeout` is a
    server setting in the startup packet, so Postgres cancels any statement that
    runs past the deadline on every connection the pool opens: the deadline
    holds for every statement of every role and no call site carries it. The
    driver's own `timeout` bounds opening a connection, so a database that
    accepts no connection fails a call within the same bound a checkout has."""
    milliseconds = round(pool.statement_timeout_seconds * 1000)
    return {
        "timeout": pool.checkout_timeout_seconds,
        "server_settings": {"statement_timeout": str(milliseconds)},
    }


def engine_for(url: str, pool: RolePool) -> AsyncEngine:
    """One engine on a URL under one role's bounds. `max_overflow` is zero, not a
    knob of its own: the declared size is then the number of connections the
    process can hold, which is the number a worker's capacity is set against, and
    a checkout past it waits `pool_timeout` and fails rather than queueing
    without end."""
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool.size,
        max_overflow=0,
        pool_timeout=pool.checkout_timeout_seconds,
        connect_args=connect_args(pool),
    )


class StoragePostgresImpl(StorageInterface):
    def __init__(
        self,
        urls: Mapping[DatabaseRole, str],
        pools: Mapping[DatabaseRole, RolePool] | None = None,
    ) -> None:
        """One engine per distinct URL and bounds: roles that share both share a
        pool, and a role given a size, a checkout bound, or a statement deadline
        of its own gets a pool of its own, which is what makes the role the
        bulkhead between two load profiles on one database. `pools` defaults to
        what settings declare, so a caller that names only URLs still runs on
        bounds from settings and never on a library default."""
        bounds = pools if pools is not None else StorageSettings().role_pools()
        engines: dict[tuple[str, RolePool], AsyncEngine] = {}
        sessions: dict[DatabaseRole, SessionFactory] = {}
        for role in DatabaseRole:
            key = (urls[role], bounds[role])
            if key not in engines:
                engines[key] = engine_for(*key)
            sessions[role] = async_sessionmaker(engines[key], expire_on_commit=False)
        self._engines = engines
        self._sessions = sessions
        self._tenancy = TenancyStoragePostgresImpl(sessions)
        self._work = WorkStoragePostgresImpl(sessions)
        self._tasks = TasksStoragePostgresImpl(sessions)
        self._idempotency = IdempotencyStoragePostgresImpl(sessions)
        self._events = EventStoragePostgresImpl(sessions)
        self._outbox = OutboxStoragePostgresImpl(sessions)

    def get_tenancy_storage(self) -> TenancyStorageInterface:
        return self._tenancy

    def get_work_storage(self) -> WorkStorageInterface:
        return self._work

    def get_tasks_storage(self) -> TasksStorageInterface:
        return self._tasks

    def get_idempotency_storage(self) -> IdempotencyStorageInterface:
        return self._idempotency

    def get_event_storage(self) -> EventStorageInterface:
        return self._events

    def get_outbox_storage(self) -> OutboxStorageInterface:
        return self._outbox

    async def healthcheck(self) -> bool:
        try:
            for engine in self._engines.values():
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    async def close(self) -> None:
        for engine in self._engines.values():
            await engine.dispose()
