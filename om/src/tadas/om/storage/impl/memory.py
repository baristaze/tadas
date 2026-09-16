"""The in-memory storage root: the default for unit tests and the fast gate."""

from tadas.om.storage.root import StorageInterface
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.impl.memory import TasksStorageMemoryImpl
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.storage.impl.memory import WorkStorageMemoryImpl


class StorageMemoryImpl(StorageInterface):
    def __init__(self) -> None:
        self._tenancy = TenancyStorageMemoryImpl()
        self._work = WorkStorageMemoryImpl()
        self._tasks = TasksStorageMemoryImpl()

    def get_tenancy_storage(self) -> TenancyStorageInterface:
        return self._tenancy

    def get_work_storage(self) -> WorkStorageInterface:
        return self._work

    def get_tasks_storage(self) -> TasksStorageInterface:
        return self._tasks

    async def healthcheck(self) -> bool:
        return True

    async def close(self) -> None:
        return None
