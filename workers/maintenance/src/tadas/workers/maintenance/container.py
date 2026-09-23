"""The worker boots the same way a service does: settings, storage, infra,
the payment processor, managers, and the Slack client. The loop holds the
container directly."""

import logging
from datetime import timedelta

from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.root import InfraInterface
from tadas.integrations.impl.configured import absent_integrations, payments_for
from tadas.integrations.payments import PaymentsInterface
from tadas.integrations.root import IntegrationsInterface
from tadas.integrations.slack import SlackInterface
from tadas.integrations.slack.off import SlackOffImpl
from tadas.integrations.slack.twin import TWIN_ENVIRONMENTS, SlackTwinImpl
from tadas.integrations.slack.web import SlackWebImpl
from tadas.om.root import Managers, build_managers
from tadas.om.storage.impl.postgres import StoragePostgresImpl
from tadas.om.storage.root import StorageInterface
from tadas.workers.maintenance.settings import MaintenanceSettings

log = logging.getLogger(__name__)


def build_slack(settings: MaintenanceSettings) -> SlackInterface:
    """The real client when a bot token is set; the twin in a local process
    without one; and, in a deployed process without one, the client that posts
    nothing and says so. The twin never runs in a deployed environment."""
    if settings.slack_bot_token is not None:
        return SlackWebImpl(
            settings.slack_bot_token, timedelta(seconds=settings.slack_timeout_seconds)
        )
    if settings.environment in TWIN_ENVIRONMENTS:
        return SlackTwinImpl(settings.environment)
    return SlackOffImpl()


class WorkerContainer:
    def __init__(
        self,
        settings: MaintenanceSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        managers: Managers,
        slack: SlackInterface,
        integrations: IntegrationsInterface,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.managers = managers
        self.slack = slack
        self.integrations = integrations

    @property
    def payments(self) -> PaymentsInterface:
        return self.integrations.get_payments()

    @classmethod
    def build(cls, settings: MaintenanceSettings) -> WorkerContainer:
        storage = StoragePostgresImpl(
            settings.role_urls(),
            settings.role_pools(),
            system_urls=settings.system_role_urls(),
        )
        infra = InfraConfiguredImpl(settings)
        # The worker signs nobody in; it reads the payment processor.
        integrations = absent_integrations(payments_for(settings, settings.environment))
        return cls(
            settings,
            storage,
            infra,
            build_managers(storage, infra, integrations=integrations),
            build_slack(settings),
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
            }
        )
        integrations = integrations or absent_integrations(
            payments_for(settings, settings.environment)
        )
        return cls(
            settings,
            storage,
            infra,
            build_managers(storage, infra, integrations=integrations),
            slack or SlackTwinImpl(settings.environment),
            integrations,
        )

    async def start(self) -> None:
        await self.infra.start()
        await self.integrations.start()
        await self.slack.start()
        log.info(
            "%s %s started with %s",
            self.settings.service_name,
            self.settings.worker_id,
            ", ".join(
                [*self.infra.describe(), *self.integrations.describe(), self.slack.describe()]
            ),
        )

    async def close(self) -> None:
        await self.slack.close()
        await self.integrations.close()
        await self.infra.close()
        await self.storage.close()
