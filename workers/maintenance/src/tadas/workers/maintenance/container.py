"""The worker boots the same way a service does: settings, storage, infra,
managers, and the Slack client. The loop holds the container directly."""

import logging
from datetime import timedelta

from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.root import InfraInterface
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
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.managers = managers
        self.slack = slack

    @classmethod
    def build(cls, settings: MaintenanceSettings) -> WorkerContainer:
        storage = StoragePostgresImpl(
            settings.role_urls(),
            settings.role_pools(),
            system_urls=settings.system_role_urls(),
        )
        infra = InfraConfiguredImpl(settings)
        return cls(settings, storage, infra, build_managers(storage, infra), build_slack(settings))

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: MaintenanceSettings | None = None,
        slack: SlackInterface | None = None,
    ) -> WorkerContainer:
        settings = settings or MaintenanceSettings.model_validate(
            {"_env_file": None, "environment": "test", "worker_id": "maintenance-test"}
        )
        return cls(
            settings,
            storage,
            infra,
            build_managers(storage, infra),
            slack or SlackTwinImpl(settings.environment),
        )

    async def start(self) -> None:
        await self.infra.start()
        await self.slack.start()
        log.info(
            "%s %s started with %s",
            self.settings.service_name,
            self.settings.worker_id,
            ", ".join([*self.infra.describe(), self.slack.describe()]),
        )

    async def close(self) -> None:
        await self.slack.close()
        await self.infra.close()
        await self.storage.close()
