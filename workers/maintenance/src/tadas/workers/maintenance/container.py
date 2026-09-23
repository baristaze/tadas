"""The worker boots the same way a service does: settings, storage, infra,
managers. The loop holds the container directly."""

import logging

from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.root import InfraInterface
from tadas.integrations.payments import PaymentsInterface
from tadas.integrations.settings import build_payments
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
        payments: PaymentsInterface,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.managers = managers
        self.payments = payments

    @classmethod
    def build(cls, settings: MaintenanceSettings) -> WorkerContainer:
        storage = StoragePostgresImpl(
            settings.role_urls(),
            settings.role_pools(),
            system_urls=settings.system_role_urls(),
        )
        infra = InfraConfiguredImpl(settings)
        payments = build_payments(settings)
        return cls(
            settings, storage, infra, build_managers(storage, infra, payments=payments), payments
        )

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: MaintenanceSettings | None = None,
        payments: PaymentsInterface | None = None,
    ) -> WorkerContainer:
        settings = settings or MaintenanceSettings.model_validate(
            {"_env_file": None, "environment": "test", "worker_id": "maintenance-test"}
        )
        payments = payments or build_payments(settings)
        return cls(
            settings, storage, infra, build_managers(storage, infra, payments=payments), payments
        )

    async def start(self) -> None:
        await self.infra.start()
        await self.payments.start()
        log.info(
            "%s %s started with %s",
            self.settings.service_name,
            self.settings.worker_id,
            ", ".join([*self.infra.describe(), self.payments.describe()]),
        )

    async def close(self) -> None:
        await self.payments.close()
        await self.infra.close()
        await self.storage.close()
