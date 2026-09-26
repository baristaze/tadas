"""The business-layer root: constructs every manager in dependency order and
hands back one frozen object with a field per manager."""

from dataclasses import dataclass

from tadas.infra.cache import CacheScope
from tadas.infra.root import InfraInterface
from tadas.integrations.identity.absent import IdentityProviderAbsentImpl
from tadas.integrations.impl.configured import absent_payments
from tadas.integrations.root import IntegrationsInterface
from tadas.integrations.slack.off import SlackOffImpl
from tadas.om.billing import BillingManagerInterface, BillingOperatorManagerInterface
from tadas.om.billing.impl.manager import BillingManagerImpl, BillingOptions
from tadas.om.billing.impl.operator import BillingOperatorManagerImpl
from tadas.om.events import EventsManagerInterface
from tadas.om.events.impl.manager import EventsManagerImpl, EventsOptions
from tadas.om.idempotency import IdempotencyManagerInterface
from tadas.om.idempotency.impl.manager import IdempotencyManagerImpl, IdempotencyOptions
from tadas.om.media import MediaManagerInterface
from tadas.om.media.impl.manager import MediaManagerImpl, MediaOptions
from tadas.om.orchestrations import OrchestrationsManagerInterface
from tadas.om.orchestrations.impl.manager import OrchestrationsManagerImpl, OrchestrationsOptions
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.impl.relay import OutboxRelayImpl
from tadas.om.slack import SlackManagerInterface
from tadas.om.slack.impl.manager import SlackManagerImpl, SlackOptions
from tadas.om.storage.root import StorageInterface
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.impl.manager import TasksManagerImpl, TasksOptions
from tadas.om.tenancy import TenancyManagerInterface, TenancyOperatorManagerInterface
from tadas.om.tenancy.impl.manager import TenancyManagerImpl, TenancyOptions
from tadas.om.tenancy.impl.operator import TenancyOperatorManagerImpl, TenancyOperatorOptions
from tadas.om.work import WorkManagerInterface
from tadas.om.work.impl.manager import WorkManagerImpl, WorkOptions


@dataclass(frozen=True)
class Managers:
    tenancy: TenancyManagerInterface
    tenancy_operator: TenancyOperatorManagerInterface
    work: WorkManagerInterface
    tasks: TasksManagerInterface
    media: MediaManagerInterface
    slack: SlackManagerInterface
    idempotency: IdempotencyManagerInterface
    events: EventsManagerInterface
    outbox: OutboxRelayInterface
    billing: BillingManagerInterface
    billing_operator: BillingOperatorManagerInterface
    orchestrations: OrchestrationsManagerInterface


def build_managers(
    storage: StorageInterface,
    infra: InfraInterface,
    tenancy_options: TenancyOptions | None = None,
    operator_options: TenancyOperatorOptions | None = None,
    integrations: IntegrationsInterface | None = None,
    tasks_options: TasksOptions | None = None,
) -> Managers:
    """`integrations` is the root of the hosted services the managers front:
    the identity provider, which the tenancy manager signs people in and
    invites them through, the payment processor, which the billing manager
    mirrors, and the Slack app, which the slack manager installs and posts
    through. None is a process that signs nobody in and holds none of them,
    and every call that would reach one is refused as unavailable.
    `tasks_options` is the worker's: the age at which the daily cleanup
    archives a done task."""
    # The relay every core-role manager hands its outbox rows to. It reaches
    # the work manager through the root below, because a row of kind
    # `work.<kind>` is enqueued there: the work manager needs the tenancy
    # manager, which needs this relay, so that one edge is bound at call time
    # and the graph the root hands back is still whole.
    outbox = OutboxRelayImpl(
        storage.get_outbox_storage(),
        storage.get_event_storage(),
        infra.get_topics(),
        lambda: managers.work,
    )
    # Billing and tenancy ask each other one question each: tenancy asks an
    # org's entitlements, and billing's sweep asks whether a tenant is past
    # its retention. That edge is bound at call time, as the relay's is.
    billing = BillingManagerImpl(
        storage.get_billing_storage(),
        absent_payments() if integrations is None else integrations.get_payments(),
        outbox,
        lambda: managers.tenancy,
        BillingOptions(),
    )
    tenancy = TenancyManagerImpl(
        storage.get_tenancy_storage(),
        outbox,
        infra.get_cache(CacheScope.REALTIME_TICKET),
        tenancy_options or TenancyOptions(),
        entitlements=billing,
        identity_provider=(
            IdentityProviderAbsentImpl()
            if integrations is None
            else integrations.get_identity_provider()
        ),
    )
    events = EventsManagerImpl(storage.get_event_storage(), tenancy, EventsOptions())
    work = WorkManagerImpl(
        storage.get_work_storage(),
        tenancy,
        events,
        infra.get_topics(),
        WorkOptions(),
    )
    media = MediaManagerImpl(
        storage.get_media_storage(),
        infra.get_buckets(),
        tenancy,
        outbox,
        MediaOptions(),
    )
    slack = SlackManagerImpl(
        storage.get_slack_storage(),
        tenancy,
        outbox,
        SlackOffImpl() if integrations is None else integrations.get_slack(),
        infra.get_secrets(),
        SlackOptions(),
    )
    orchestrations = OrchestrationsManagerImpl(
        storage.get_orchestrations_storage(), tenancy, outbox, OrchestrationsOptions()
    )
    tasks = TasksManagerImpl(
        storage.get_tasks_storage(),
        tenancy,
        media,
        outbox,
        slack,
        tasks_options or TasksOptions(),
        entitlements=billing,
        orchestrations=orchestrations,
    )
    idempotency = IdempotencyManagerImpl(storage.get_idempotency_storage(), IdempotencyOptions())
    tenancy_operator = TenancyOperatorManagerImpl(
        storage.get_tenancy_storage(),
        storage.get_tasks_storage(),
        storage.get_event_storage(),
        outbox,
        operator_options or TenancyOperatorOptions(),
        billing=storage.get_billing_storage(),
    )
    managers = Managers(
        tenancy=tenancy,
        tenancy_operator=tenancy_operator,
        work=work,
        tasks=tasks,
        media=media,
        slack=slack,
        idempotency=idempotency,
        events=events,
        outbox=outbox,
        billing=billing,
        billing_operator=BillingOperatorManagerImpl(
            storage.get_billing_storage(), storage.get_tenancy_storage(), outbox
        ),
        orchestrations=orchestrations,
    )
    return managers
