"""The worker boots the same way a service does: settings, storage, infra,
the integrations (the payment processor and the Slack app), and managers.
The loop holds the container directly."""

import logging

from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.root import InfraInterface
from tadas.integrations.impl.configured import absent_integrations, payments_for, slack_for
from tadas.integrations.payments import PaymentsInterface
from tadas.integrations.root import IntegrationsInterface
from tadas.integrations.slack import SlackInterface
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
        integrations: IntegrationsInterface,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.managers = managers
        self.integrations = integrations

    @property
    def payments(self) -> PaymentsInterface:
        return self.integrations.get_payments()

    @property
    def slack(self) -> SlackInterface:
        return self.integrations.get_slack()

    @classmethod
    def build(cls, settings: MaintenanceSettings) -> WorkerContainer:
        storage = StoragePostgresImpl(
            settings.role_urls(),
            settings.role_pools(),
            system_urls=settings.system_role_urls(),
        )
        infra = InfraConfiguredImpl(settings)
        # The worker signs nobody in; it reads the payment processor and
        # posts through the Slack app.
        integrations = absent_integrations(
            payments_for(settings, settings.environment),
            slack_for(settings, settings.environment),
        )
        return cls(
            settings,
            storage,
            infra,
            build_managers(storage, infra, integrations=integrations),
            integrations,
        )

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: MaintenanceSettings | None = None,
        slack: SlackInterface | None = None,
        integrations: IntegrationsInterface | None = None,
    ) -> WorkerContainer:
        settings = settings or MaintenanceSettings.model_validate(
            {
                "_env_file": None,
                "environment": "test",
                "worker_id": "maintenance-test",
                "billing_backend": "twin",
                "slack_backend": "twin",
            }
        )
        integrations = integrations or absent_integrations(
            payments_for(settings, settings.environment),
            slack or slack_for(settings, settings.environment),
        )
        return cls(
            settings,
            storage,
            infra,
            build_managers(storage, infra, integrations=integrations),
            integrations,
        )

    async def start(self) -> None:
        await self.infra.start()
        await self.integrations.start()
        log.info(
            "%s %s started with %s",
            self.settings.service_name,
            self.settings.worker_id,
            ", ".join([*self.infra.describe(), *self.integrations.describe()]),
        )

    async def close(self) -> None:
        await self.integrations.close()
        await self.infra.close()
        await self.storage.close()
