"""The business-layer root: constructs every manager in dependency order and
hands back one frozen object with a field per manager."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from tadas.infra.buckets import BucketsInterface
from tadas.infra.cache import CacheInterface, CacheScope
from tadas.infra.cache.read import ReadCache
from tadas.infra.root import InfraInterface
from tadas.integrations.identity import IdentityProviderInterface
from tadas.integrations.identity.absent import IdentityProviderAbsentImpl
from tadas.integrations.impl.configured import absent_payments
from tadas.integrations.root import IntegrationsInterface
from tadas.integrations.slack.off import SlackOffImpl
from tadas.om.base import utcnow
from tadas.om.billing import BillingManagerInterface, BillingOperatorManagerInterface
from tadas.om.billing.impl.manager import BillingManagerImpl, BillingOptions, cached_accounts
from tadas.om.billing.impl.operator import BillingOperatorManagerImpl
from tadas.om.billing.kinds import BILLING_KINDS
from tadas.om.billing.manager import EntitlementsInterface
from tadas.om.billing.types.account import BillingAccount
from tadas.om.change_events import ChangeEventsManagerInterface
from tadas.om.change_events.impl.manager import ChangeEventsManagerImpl, ChangeEventsOptions
from tadas.om.idempotency import IdempotencyManagerInterface
from tadas.om.idempotency.impl.manager import IdempotencyManagerImpl, IdempotencyOptions
from tadas.om.leases import LeasesManagerInterface
from tadas.om.leases.impl.kinds import NoopLeasableResourceKindImpl, OrchestrationWaiterImpl
from tadas.om.leases.impl.manager import LeasesManagerImpl, LeasesOptions
from tadas.om.leases.types.leasable_resource import LeasableResourceKind
from tadas.om.leases.types.request import WaiterKind
from tadas.om.media import MediaManagerInterface
from tadas.om.media.impl.manager import MediaManagerImpl, MediaOptions
from tadas.om.orchestrations import OrchestrationsManagerInterface
from tadas.om.orchestrations.impl.manager import OrchestrationsManagerImpl, OrchestrationsOptions
from tadas.om.orchestrations.kinds import NOOP_ORCHESTRATION, OrchestrationKinds
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.impl.relay import OutboxRelayImpl
from tadas.om.slack import SlackManagerInterface
from tadas.om.slack.impl.manager import SlackManagerImpl, SlackOptions
from tadas.om.slack.kinds import SLACK_KINDS
from tadas.om.storage.root import StorageInterface
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.impl.attachments import TasksAttachmentsManagerImpl
from tadas.om.tasks.impl.cleanup import TasksCleanupManagerImpl
from tadas.om.tasks.impl.imports import TasksImportsManagerImpl
from tadas.om.tasks.impl.manager import TasksManagerImpl, TasksOptions
from tadas.om.tasks.impl.reminders import TasksRemindersManagerImpl
from tadas.om.tasks.kinds import TASKS_KINDS, TASKS_ORCHESTRATION_KINDS
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tenancy import TenancyManagerInterface, TenancyOperatorManagerInterface
from tadas.om.tenancy.impl.credentials import TenancyCredentialsManagerImpl
from tadas.om.tenancy.impl.manager import TenancyManagerImpl, TenancyOptions
from tadas.om.tenancy.impl.members import TenancyMembersManagerImpl
from tadas.om.tenancy.impl.operator import TenancyOperatorManagerImpl, TenancyOperatorOptions
from tadas.om.tenancy.impl.org import TenancyOrgManagerImpl
from tadas.om.tenancy.impl.sign_in import TenancySignInManagerImpl
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.work import WorkManagerInterface, WorkOperatorManagerInterface
from tadas.om.work.impl.manager import WorkManagerImpl, WorkOptions
from tadas.om.work.impl.operator import WorkOperatorManagerImpl
from tadas.om.work.kinds import WORK_KINDS, WorkKinds

KINDS = WorkKinds(
    (
        *WORK_KINDS,
        # A copy adds its entries below this line.
        *BILLING_KINDS,
        *SLACK_KINDS,
        *TASKS_KINDS,
    )
)
"""Every kind of work this process knows: the work namespace's own, then
each namespace's that declares kinds in its own `kinds.py`. The work
manager reads every kind through it, and the worker holds its handlers to
it."""

ORCHESTRATION_KINDS = OrchestrationKinds(
    (
        NOOP_ORCHESTRATION,
        # A copy adds its entries below this line.
        *TASKS_ORCHESTRATION_KINDS,
    )
)
"""Every kind of long-running record this process knows: the mechanism's
own, then each namespace's that declares kinds in its own `kinds.py`. The
orchestrations manager holds every start to it, and the worker holds its
steps to it."""


@dataclass(frozen=True)
class Managers:
    change_events: ChangeEventsManagerInterface
    idempotency: IdempotencyManagerInterface
    leases: LeasesManagerInterface
    media: MediaManagerInterface
    orchestrations: OrchestrationsManagerInterface
    outbox: OutboxRelayInterface
    tenancy: TenancyManagerInterface
    tenancy_operator: TenancyOperatorManagerInterface
    work: WorkManagerInterface
    work_operator: WorkOperatorManagerInterface
    # A copy adds its entries below this line.
    billing: BillingManagerInterface
    billing_operator: BillingOperatorManagerInterface
    slack: SlackManagerInterface
    tasks: TasksManagerInterface


def build_managers(
    storage: StorageInterface,
    infra: InfraInterface,
    tenancy_options: TenancyOptions | None = None,
    operator_options: TenancyOperatorOptions | None = None,
    integrations: IntegrationsInterface | None = None,
    *,
    change_events_options: ChangeEventsOptions | None = None,
    idempotency_options: IdempotencyOptions | None = None,
    leases_options: LeasesOptions | None = None,
    media_options: MediaOptions | None = None,
    orchestration_kinds: OrchestrationKinds = ORCHESTRATION_KINDS,
    orchestrations_options: OrchestrationsOptions | None = None,
    work_kinds: WorkKinds = KINDS,
    work_options: WorkOptions | None = None,
    # A copy adds its entries below this line.
    billing_options: BillingOptions | None = None,
    slack_options: SlackOptions | None = None,
    tasks_options: TasksOptions | None = None,
) -> Managers:
    """`integrations` is the root of the hosted services the managers front:
    the identity provider, which the tenancy manager signs people in and
    invites them through, the payment processor, which the billing manager
    mirrors, and the Slack app, which the slack manager installs and posts
    through. None is a process that signs nobody in and holds none of them,
    and every call that would reach one is refused as unavailable.

    The options after `integrations` are what the process that sweeps sets
    on the managers it purges through: each one's retention and batch, and
    the tasks manager's age at which the daily cleanup archives a done
    task. None keeps that manager's defaults. `work_kinds` and `orchestration_kinds`
    are the registries the work and the orchestrations managers read every
    kind through: `KINDS` and `ORCHESTRATION_KINDS`, unless a test hands
    another.

    Each manager is one call to its builder below, in dependency order: a
    builder takes the storage, the infrastructure, and the sibling managers
    it needs, by their interfaces, and nothing else."""
    # The relay every core-role manager hands its outbox rows to. It reaches
    # the work manager through the root below, because a row of kind
    # `work.<kind>` is enqueued there: the work manager needs the tenancy
    # manager, which needs this relay, so that one edge is bound at call time
    # and the graph the root hands back is still whole.
    outbox = build_outbox(storage, infra, lambda: managers.work)
    # Billing and tenancy ask each other one question each: tenancy asks an
    # org's entitlements, and billing's sweep asks whether a tenant is past
    # its retention. That edge is bound at call time, as the relay's is. Both
    # billing planes take the one reader of the org's account: the tenant
    # plane reads through it, and the operator plane's grant bumps it.
    billing_options = billing_options or BillingOptions()
    accounts = cached_accounts(
        infra.get_cache(CacheScope.BILLING_ACCOUNT), billing_options.account_ttl
    )
    billing = build_billing(
        storage, integrations, outbox, lambda: managers.tenancy, accounts, billing_options
    )
    tenancy = build_tenancy(
        storage.get_tenancy_storage(),
        outbox,
        infra.get_cache(CacheScope.REALTIME_TICKET),
        tenancy_options or TenancyOptions(),
        identity_provider=(
            IdentityProviderAbsentImpl()
            if integrations is None
            else integrations.get_identity_provider()
        ),
        entitlements=billing,
    )
    tenancy_operator = build_tenancy_operator(
        storage, outbox, operator_options or TenancyOperatorOptions()
    )
    change_events = build_change_events(
        storage, tenancy, change_events_options or ChangeEventsOptions()
    )
    work = build_work(
        storage, infra, tenancy, change_events, work_options or WorkOptions(), work_kinds
    )
    work_operator = build_work_operator(storage, infra)
    media = build_media(storage, infra, tenancy, outbox, media_options or MediaOptions())
    orchestrations = build_orchestrations(
        storage,
        tenancy,
        outbox,
        orchestrations_options or OrchestrationsOptions(),
        orchestration_kinds,
    )
    leases = build_leases(
        storage, tenancy, outbox, work, orchestrations, leases_options or LeasesOptions()
    )
    idempotency = build_idempotency(storage, idempotency_options or IdempotencyOptions())
    # A copy adds its entries below this line.
    slack = build_slack(
        storage, infra, tenancy, outbox, integrations, slack_options or SlackOptions()
    )
    tasks = build_tasks(
        storage.get_tasks_storage(),
        tenancy,
        media,
        outbox,
        slack,
        tasks_options or TasksOptions(),
        buckets=infra.get_buckets(),
        entitlements=billing,
        orchestrations=orchestrations,
    )
    billing_operator = build_billing_operator(storage, outbox, accounts)
    managers = Managers(
        change_events=change_events,
        idempotency=idempotency,
        leases=leases,
        media=media,
        orchestrations=orchestrations,
        outbox=outbox,
        tenancy=tenancy,
        tenancy_operator=tenancy_operator,
        work=work,
        work_operator=work_operator,
        # A copy adds its entries below this line.
        billing=billing,
        billing_operator=billing_operator,
        slack=slack,
        tasks=tasks,
    )
    return managers


def build_change_events(
    storage: StorageInterface, tenancy: TenancyManagerInterface, options: ChangeEventsOptions
) -> ChangeEventsManagerInterface:
    return ChangeEventsManagerImpl(storage.get_change_event_storage(), tenancy, options)


def build_idempotency(
    storage: StorageInterface, options: IdempotencyOptions
) -> IdempotencyManagerInterface:
    return IdempotencyManagerImpl(storage.get_idempotency_storage(), options)


def build_leases(
    storage: StorageInterface,
    tenancy: TenancyManagerInterface,
    outbox: OutboxRelayInterface,
    work: WorkManagerInterface,
    orchestrations: OrchestrationsManagerInterface,
    options: LeasesOptions,
) -> LeasesManagerInterface:
    """A copy registers its resource kinds and its waiter kinds here, below
    the marker, each by the name its namespace declares with its hooks, as a
    work kind's handler is registered in the worker, and, for a kind that
    refuses some asks, its check (`asks`)."""
    return LeasesManagerImpl(
        storage.get_lease_storage(),
        tenancy,
        outbox,
        options,
        kinds={
            LeasableResourceKind.NOOP: NoopLeasableResourceKindImpl(),
            # A copy adds its entries below this line.
        },
        waiters={
            WaiterKind.ORCHESTRATION: OrchestrationWaiterImpl(orchestrations),
            # A copy adds its entries below this line.
        },
        work=work,
    )


def build_media(
    storage: StorageInterface,
    infra: InfraInterface,
    tenancy: TenancyManagerInterface,
    outbox: OutboxRelayInterface,
    options: MediaOptions,
) -> MediaManagerInterface:
    return MediaManagerImpl(
        storage.get_media_storage(),
        infra.get_buckets(),
        tenancy,
        outbox,
        infra.get_flags(),
        options,
    )


def build_orchestrations(
    storage: StorageInterface,
    tenancy: TenancyManagerInterface,
    outbox: OutboxRelayInterface,
    options: OrchestrationsOptions,
    kinds: OrchestrationKinds,
) -> OrchestrationsManagerInterface:
    return OrchestrationsManagerImpl(
        storage.get_orchestrations_storage(), tenancy, outbox, options, kinds
    )


def build_outbox(
    storage: StorageInterface,
    infra: InfraInterface,
    work: Callable[[], WorkManagerInterface],
) -> OutboxRelayInterface:
    """`work` is called when a row asks for work, never here: the work
    manager is built after the relay it is reached through."""
    return OutboxRelayImpl(
        storage.get_outbox_storage(),
        storage.get_change_event_storage(),
        infra.get_topics(),
        work,
    )


def build_tenancy(
    storage: TenancyStorageInterface,
    relay: OutboxRelayInterface,
    cache: CacheInterface,
    options: TenancyOptions,
    clock: Callable[[], datetime] = utcnow,
    *,
    identity_provider: IdentityProviderInterface,
    entitlements: EntitlementsInterface,
) -> TenancyManagerInterface:
    """The tenancy manager with its delegates, each built here and handed to
    it: a caller outside the namespace reaches a delegate through the
    manager, and no impl builds another. A delegate that calls a sibling
    takes it here, by its interface, and one that needs an operation of the
    manager takes that one operation as a callable. `clock` is the one the
    second factor's time step is read from. `entitlements` is what the plan
    levers ask: an api key and a per-seat plan's seat count read the org's
    plan from it."""
    # A person who joins by invitation or by single sign-on is asked for a
    # seat under the org's service context, which comes only from the
    # manager's transition, bound at call time as the org delegate's is.
    sign_in = TenancySignInManagerImpl(
        storage,
        relay,
        options,
        clock,
        identity_provider=identity_provider,
        entitlements=entitlements,
        service_context=lambda rctx, org_id, user_id: tenancy.service_context(
            rctx, org_id, user_id
        ),
    )
    # The account's deletion writes a row under each place its person holds,
    # and a stage comes only from the manager's transition. The manager holds
    # this delegate, so that one edge is bound at call time.
    org = TenancyOrgManagerImpl(
        storage,
        relay,
        options,
        identity_provider=identity_provider,
        entitlements=entitlements,
        service_context=lambda rctx, org_id, user_id: tenancy.service_context(
            rctx, org_id, user_id
        ),
    )
    members = TenancyMembersManagerImpl(
        storage,
        relay,
        options,
        org=org,
        identity_provider=identity_provider,
        entitlements=entitlements,
    )
    credentials = TenancyCredentialsManagerImpl(storage, relay, options, entitlements=entitlements)
    tenancy = TenancyManagerImpl(
        storage,
        relay,
        cache,
        options,
        entitlements=entitlements,
        sign_in=sign_in,
        org=org,
        members=members,
        credentials=credentials,
    )
    return tenancy


def build_tenancy_operator(
    storage: StorageInterface, outbox: OutboxRelayInterface, options: TenancyOperatorOptions
) -> TenancyOperatorManagerInterface:
    return TenancyOperatorManagerImpl(
        storage.get_tenancy_storage(),
        storage.get_tasks_storage(),
        storage.get_change_event_storage(),
        outbox,
        options,
        billing=storage.get_billing_storage(),
    )


def build_work(
    storage: StorageInterface,
    infra: InfraInterface,
    tenancy: TenancyManagerInterface,
    change_events: ChangeEventsManagerInterface,
    options: WorkOptions,
    kinds: WorkKinds,
) -> WorkManagerInterface:
    return WorkManagerImpl(
        storage.get_work_storage(), tenancy, change_events, infra.get_topics(), options, kinds
    )


def build_work_operator(
    storage: StorageInterface, infra: InfraInterface
) -> WorkOperatorManagerInterface:
    return WorkOperatorManagerImpl(
        storage.get_work_storage(),
        storage.get_tenancy_storage(),
        storage.get_change_event_storage(),
        infra.get_topics(),
    )


# A copy adds its entries below this line.


def build_billing(
    storage: StorageInterface,
    integrations: IntegrationsInterface | None,
    outbox: OutboxRelayInterface,
    tenancy: Callable[[], TenancyManagerInterface],
    accounts: ReadCache[BillingAccount | None],
    options: BillingOptions,
) -> BillingManagerInterface:
    """`tenancy` is called when billing's sweep asks a tenant's retention,
    never here: the tenancy manager is built after the billing manager whose
    entitlements it reads."""
    return BillingManagerImpl(
        storage.get_billing_storage(),
        absent_payments() if integrations is None else integrations.get_payments(),
        outbox,
        tenancy,
        accounts,
        options,
    )


def build_billing_operator(
    storage: StorageInterface,
    outbox: OutboxRelayInterface,
    accounts: ReadCache[BillingAccount | None],
) -> BillingOperatorManagerInterface:
    return BillingOperatorManagerImpl(
        storage.get_billing_storage(), storage.get_tenancy_storage(), outbox, accounts
    )


def build_slack(
    storage: StorageInterface,
    infra: InfraInterface,
    tenancy: TenancyManagerInterface,
    outbox: OutboxRelayInterface,
    integrations: IntegrationsInterface | None,
    options: SlackOptions,
) -> SlackManagerInterface:
    return SlackManagerImpl(
        storage.get_slack_storage(),
        tenancy,
        outbox,
        SlackOffImpl() if integrations is None else integrations.get_slack(),
        infra.get_secrets(),
        options,
    )


def build_tasks(
    storage: TasksStorageInterface,
    tenancy: TenancyManagerInterface,
    media: MediaManagerInterface,
    relay: OutboxRelayInterface,
    slack: SlackManagerInterface,
    options: TasksOptions,
    *,
    buckets: BucketsInterface,
    entitlements: EntitlementsInterface,
    orchestrations: OrchestrationsManagerInterface,
) -> TasksManagerInterface:
    """The tasks manager with its delegates, each built here and handed to
    it, as `build_tenancy` builds the tenancy manager's. `entitlements` is
    what the plan's bound on active tasks is read from, `orchestrations`
    keeps the records of an import and of a cleanup, and `buckets` is the
    store an import reads its stored file from."""
    # An attachment is a live task's, and the read of one is the manager's.
    # The manager holds this delegate, so that one edge is bound at call time.
    attachments = TasksAttachmentsManagerImpl(
        media, get_task=lambda ctx, task_id: tasks.get_task(ctx, task_id)
    )
    imports = TasksImportsManagerImpl(
        storage,
        tenancy,
        media,
        relay,
        options,
        buckets=buckets,
        entitlements=entitlements,
        orchestrations=orchestrations,
    )
    cleanup = TasksCleanupManagerImpl(storage, relay, options, orchestrations=orchestrations)
    reminders = TasksRemindersManagerImpl(storage, tenancy, relay, slack)
    tasks = TasksManagerImpl(
        storage,
        tenancy,
        media,
        relay,
        slack,
        options,
        entitlements=entitlements,
        attachments=attachments,
        imports=imports,
        cleanup=cleanup,
        reminders=reminders,
    )
    return tasks
