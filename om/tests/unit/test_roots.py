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


async def test_postgres_root_opens_one_engine_per_distinct_url() -> None:
    shared = "postgresql+asyncpg://tadas:tadas@127.0.0.1:55432/tadas"
    # Both arguments come from a settings object, the way a composition root
    # hands them over; the impl reads nothing itself.
    pools = StorageSettings(database_url=shared).role_pools()
    root = StoragePostgresImpl(dict.fromkeys(DatabaseRole, shared), pools)
    assert isinstance(root.get_tenancy_storage(), TenancyStorageInterface)
    assert len(root._engines) == 1
    await root.close()

    split = dict.fromkeys(DatabaseRole, shared)
    split[DatabaseRole.QUEUE] = "postgresql+asyncpg://tadas:tadas@127.0.0.1:55432/tadas_queue"
    root = StoragePostgresImpl(split, pools)
    assert len(root._engines) == 2
    await root.close()


def test_role_urls_default_to_the_shared_one() -> None:
    settings = StorageSettings(
        database_url="postgresql+asyncpg://x@127.0.0.1/a",
        database_url_queue="postgresql+asyncpg://x@127.0.0.1/q",
    )
    urls = settings.role_urls()
    assert urls[DatabaseRole.CORE].endswith("/a")
    assert urls[DatabaseRole.QUEUE].endswith("/q")


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
