"""The relational storage root: one engine and pool per distinct role URL,
every namespace impl constructed here."""

from collections.abc import Mapping

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
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.impl.postgres import TasksStoragePostgresImpl
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.postgres import TenancyStoragePostgresImpl
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.storage.impl.postgres import WorkStoragePostgresImpl


class StoragePostgresImpl(StorageInterface):
    def __init__(self, urls: Mapping[DatabaseRole, str]) -> None:
        engines: dict[str, AsyncEngine] = {}
        sessions: dict[DatabaseRole, SessionFactory] = {}
        for role in DatabaseRole:
            url = urls[role]
            if url not in engines:
                engines[url] = create_async_engine(url, pool_pre_ping=True)
            sessions[role] = async_sessionmaker(engines[url], expire_on_commit=False)
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
