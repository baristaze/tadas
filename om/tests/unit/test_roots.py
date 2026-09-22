from pathlib import Path

from tadas.infra.impl.local import InfraLocalImpl
from tadas.om.events import EventsManagerInterface
from tadas.om.events.storage import EventStorageInterface
from tadas.om.idempotency import IdempotencyManagerInterface
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.root import build_managers
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.storage.impl.postgres import StoragePostgresImpl
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import StorageSettings
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tenancy import TenancyManagerInterface, TenancyOperatorManagerInterface
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.work import WorkManagerInterface
from tadas.om.work.storage import WorkStorageInterface


async def test_memory_root_serves_every_storage() -> None:
    root = StorageMemoryImpl()
    assert isinstance(root.get_tenancy_storage(), TenancyStorageInterface)
    assert isinstance(root.get_work_storage(), WorkStorageInterface)
    assert isinstance(root.get_tasks_storage(), TasksStorageInterface)
    assert isinstance(root.get_idempotency_storage(), IdempotencyStorageInterface)
    assert isinstance(root.get_event_storage(), EventStorageInterface)
    assert await root.healthcheck() is True
    await root.close()


async def test_postgres_root_opens_one_engine_per_distinct_url_and_login() -> None:
    shared = "postgresql+asyncpg://tadas_runtime:r@127.0.0.1:55432/tadas"
    system = "postgresql+asyncpg://tadas_system:s@127.0.0.1:55432/tadas"
    # Every argument comes from a settings object, the way a composition root
    # hands them over; the impl reads nothing itself.
    settings = StorageSettings(database_url=shared, database_system_url=system)
    pools = settings.role_pools()
    root = StoragePostgresImpl(settings.role_urls(), pools, system_urls=settings.system_role_urls())
    assert isinstance(root.get_tenancy_storage(), TenancyStorageInterface)
    # One pool under the runtime login and one under the system login.
    assert len(root._engines) == 2
    await root.close()

    split = StorageSettings(
        database_url=shared,
        database_system_url=system,
        database_url_queue="postgresql+asyncpg://tadas_runtime:r@127.0.0.1:55432/tadas_queue",
    )
    root = StoragePostgresImpl(split.role_urls(), pools, system_urls=split.system_role_urls())
    assert len(root._engines) == 4
    await root.close()


def test_role_urls_default_to_the_shared_one() -> None:
    settings = StorageSettings(
        database_url="postgresql+asyncpg://x@127.0.0.1/a",
        database_url_queue="postgresql+asyncpg://x@127.0.0.1/q",
    )
    urls = settings.role_urls()
    assert urls[DatabaseRole.CORE].endswith("/a")
    assert urls[DatabaseRole.QUEUE].endswith("/q")


def test_the_system_login_follows_a_role_to_its_own_database() -> None:
    settings = StorageSettings(
        database_url="postgresql+asyncpg://tadas_runtime:r@db-a:5432/a",
        database_url_queue="postgresql+asyncpg://tadas_runtime:r@db-q:5432/q",
        database_system_url="postgresql+asyncpg://tadas_system:s@db-a:5432/a",
    )
    system = settings.system_role_urls()
    assert system[DatabaseRole.CORE] == "postgresql+asyncpg://tadas_system:s@db-a:5432/a"
    assert system[DatabaseRole.QUEUE] == "postgresql+asyncpg://tadas_system:s@db-q:5432/q"


def test_business_root_has_a_field_per_manager(tmp_path: Path) -> None:
    managers = build_managers(StorageMemoryImpl(), InfraLocalImpl(tmp_path))
    assert isinstance(managers.tenancy, TenancyManagerInterface)
    assert isinstance(managers.tenancy_operator, TenancyOperatorManagerInterface)
    assert isinstance(managers.work, WorkManagerInterface)
    assert isinstance(managers.tasks, TasksManagerInterface)
    assert isinstance(managers.idempotency, IdempotencyManagerInterface)
    assert isinstance(managers.events, EventsManagerInterface)


def test_the_system_scope_is_the_same_value_on_both_sides() -> None:
    # Infra compares the scope by value rather than importing the model.
    from tadas.infra.base import SYSTEM_SCOPE
    from tadas.om.base import EMPTY_UUID

    assert SYSTEM_SCOPE == EMPTY_UUID
