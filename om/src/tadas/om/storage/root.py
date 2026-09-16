"""Storage implementations are assembled behind a single root."""

from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.work.storage import WorkStorageInterface


class StorageInterface:
    def get_tenancy_storage(self) -> TenancyStorageInterface: ...

    def get_work_storage(self) -> WorkStorageInterface: ...

    def get_tasks_storage(self) -> TasksStorageInterface: ...

    async def healthcheck(self) -> bool: ...

    async def close(self) -> None: ...
