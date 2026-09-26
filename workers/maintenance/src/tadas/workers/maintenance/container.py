"""The worker boots the same way a service does: settings, storage, infra,
the integrations (the identity provider, the payment processor, and the
Slack app), and managers.
The loop holds the container directly."""

import logging
from datetime import timedelta

from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.root import InfraInterface
from tadas.integrations.identity import IdentityProviderInterface
from tadas.integrations.identity.twin import IdentityProviderTwinImpl
from tadas.integrations.impl.configured import (
    IntegrationsConfiguredImpl,
    IntegrationsOverImpl,
    payments_for,
    slack_for,
)
from tadas.integrations.payments import PaymentsInterface
from tadas.integrations.root import IntegrationsInterface
from tadas.integrations.slack import SlackInterface
from tadas.om.billing.impl.manager import BillingOptions
from tadas.om.events.impl.manager import EventsOptions
from tadas.om.idempotency.impl.manager import IdempotencyOptions
from tadas.om.media.impl.manager import MediaOptions
from tadas.om.orchestrations.impl.manager import OrchestrationsOptions
from tadas.om.root import Managers, build_managers
from tadas.om.slack.impl.manager import SlackOptions
from tadas.om.storage.impl.postgres import StoragePostgresImpl
from tadas.om.storage.root import StorageInterface
from tadas.om.tasks.impl.manager import TasksOptions
from tadas.om.tenancy.impl.manager import TenancyOptions
from tadas.om.work.impl.manager import WorkOptions
from tadas.workers.maintenance.settings import MaintenanceSettings

log = logging.getLogger(__name__)

MEDIA_PURGE_BATCH = 100
"""Files one media purge erases. Each is an object deleted from the store, one
request apiece, before its row, so the batch is smaller than the rows'."""


def events_options(settings: MaintenanceSettings) -> EventsOptions:
    """The sweep's trim of each living org's stream, 90 days by default and
    off at 0, a batch per call like every purge."""
    days = settings.event_retention_days
    return EventsOptions(
        retention=timedelta(days=days) if days else None, purge_batch=settings.worker_purge_batch
    )


def worker_managers(
    storage: StorageInterface,
    infra: InfraInterface,
    integrations: IntegrationsInterface,
    settings: MaintenanceSettings,
) -> Managers:
    """The managers, each one the sweep purges through with its retention and
    its batch from the settings. The worker is the one process that purges,
    so it is the one that sets them."""
    batch = settings.worker_purge_batch
    return build_managers(
        storage,
        infra,
        TenancyOptions(
            retention=timedelta(days=settings.tenancy_retention_days),
            ticket_retention=timedelta(hours=settings.socket_ticket_retention_hours),
            sign_in_delay_retention=timedelta(hours=settings.sign_in_delay_retention_hours),
            purge_batch=batch,
        ),
        integrations=integrations,
        tasks_options=TasksOptions(
            retention=timedelta(days=settings.tasks_retention_days),
            purge_batch=batch,
            archive_after=timedelta(days=settings.tasks_archive_after_days),
        ),
        media_options=MediaOptions(
            retention=timedelta(days=settings.media_retention_days),
            pending_expiry=timedelta(hours=settings.media_pending_expiry_hours),
            purge_batch=MEDIA_PURGE_BATCH,
        ),
        idempotency_options=IdempotencyOptions(
            retention=timedelta(hours=settings.idempotency_retention_hours), purge_batch=batch
        ),
        events_options=events_options(settings),
        billing_options=BillingOptions(
            retention=timedelta(days=settings.billing_delivery_retention_days),
            purge_batch=batch,
            account_ttl=timedelta(seconds=settings.billing_account_cache_seconds),
        ),
        slack_options=SlackOptions(
            retention=timedelta(days=settings.slack_retention_days), purge_batch=batch
        ),
        work_options=WorkOptions(
            retention=timedelta(days=settings.work_retention_days), purge_batch=batch
        ),
        orchestrations_options=OrchestrationsOptions(purge_batch=batch),
    )


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

    @property
    def identity_provider(self) -> IdentityProviderInterface:
        return self.integrations.get_identity_provider()

    @classmethod
    def build(cls, settings: MaintenanceSettings) -> WorkerContainer:
        storage = StoragePostgresImpl(
            settings.role_urls(),
            settings.role_pools(),
            system_urls=settings.system_role_urls(),
        )
        infra = InfraConfiguredImpl(settings)
        # The worker signs nobody in. It reads the payment processor, posts
        # through the Slack app, and deletes a deleted account's person at the
        # identity provider, so it holds all three, refused as the API's are.
        integrations = IntegrationsConfiguredImpl(
            settings, settings.environment, settings.is_cloud_environment
        )
        return cls(
            settings,
            storage,
            infra,
            worker_managers(storage, infra, integrations, settings),
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
        integrations = integrations or IntegrationsOverImpl(
            IdentityProviderTwinImpl(),
            payments_for(settings, settings.environment),
            slack or slack_for(settings, settings.environment),
        )
        return cls(
            settings,
            storage,
            infra,
            worker_managers(storage, infra, integrations, settings),
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
