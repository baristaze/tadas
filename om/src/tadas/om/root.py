"""The business-layer root: constructs every manager in dependency order and
hands back one frozen object with a field per manager."""

from dataclasses import dataclass

from tadas.infra.cache import CacheScope
from tadas.infra.root import InfraInterface
from tadas.om.events import EventsManagerInterface
from tadas.om.events.impl.manager import EventsManagerImpl, EventsOptions
from tadas.om.idempotency import IdempotencyManagerInterface
from tadas.om.idempotency.impl.manager import IdempotencyManagerImpl, IdempotencyOptions
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.impl.relay import OutboxRelayImpl
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
    idempotency: IdempotencyManagerInterface
    events: EventsManagerInterface
    outbox: OutboxRelayInterface


def build_managers(storage: StorageInterface, infra: InfraInterface) -> Managers:
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
    tenancy = TenancyManagerImpl(
        storage.get_tenancy_storage(),
        outbox,
        infra.get_cache(CacheScope.REALTIME_TICKET),
        TenancyOptions(),
    )
    events = EventsManagerImpl(storage.get_event_storage(), tenancy, EventsOptions())
    work = WorkManagerImpl(
        storage.get_work_storage(),
        tenancy,
        events,
        infra.get_topics(),
        WorkOptions(),
    )
    tasks = TasksManagerImpl(
        storage.get_tasks_storage(),
        tenancy,
        outbox,
        TasksOptions(),
    )
    idempotency = IdempotencyManagerImpl(storage.get_idempotency_storage(), IdempotencyOptions())
    tenancy_operator = TenancyOperatorManagerImpl(
        storage.get_tenancy_storage(),
        storage.get_tasks_storage(),
        storage.get_event_storage(),
        outbox,
        TenancyOperatorOptions(),
    )
    managers = Managers(
        tenancy=tenancy,
        tenancy_operator=tenancy_operator,
        work=work,
        tasks=tasks,
        idempotency=idempotency,
        events=events,
        outbox=outbox,
    )
    return managers
