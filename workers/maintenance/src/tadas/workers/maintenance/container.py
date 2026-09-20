"""The worker boots the same way a service does: settings, storage, infra,
managers. The loop holds the container directly."""

import logging

from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.root import InfraInterface
from tadas.om.root import Managers, build_managers
from tadas.om.storage.impl.postgres import StoragePostgresImpl
from tadas.om.storage.root import StorageInterface
from tadas.workers.maintenance.settings import MaintenanceSettings

log = logging.getLogger(__name__)


class WorkerContainer:
    def __init__(
        self,
        settings: MaintenanceSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        managers: Managers,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.managers = managers

    @classmethod
    def build(cls, settings: MaintenanceSettings) -> WorkerContainer:
        storage = StoragePostgresImpl(settings.role_urls(), settings.role_pools())
        infra = InfraConfiguredImpl(settings)
        return cls(settings, storage, infra, build_managers(storage, infra))

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: MaintenanceSettings | None = None,
    ) -> WorkerContainer:
        settings = settings or MaintenanceSettings.model_validate(
            {"environment": "test", "worker_id": "maintenance-test"}
        )
        return cls(settings, storage, infra, build_managers(storage, infra))

    async def start(self) -> None:
        await self.infra.start()
        log.info(
            "%s %s started with %s",
            self.settings.service_name,
            self.settings.worker_id,
            ", ".join(self.infra.describe()),
        )

    async def close(self) -> None:
        await self.infra.close()
        await self.storage.close()
