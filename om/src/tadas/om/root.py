"""The business-layer root: constructs every manager in dependency order and
hands back one frozen object with a field per manager."""

from dataclasses import dataclass

from tadas.infra.cache import CacheScope
from tadas.infra.root import InfraInterface
from tadas.om.events import EventsManagerInterface
from tadas.om.events.impl.manager import EventsManagerImpl, EventsOptions
from tadas.om.idempotency import IdempotencyManagerInterface
from tadas.om.idempotency.impl.manager import IdempotencyManagerImpl
from tadas.om.storage.root import StorageInterface
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.impl.manager import TasksManagerImpl, TasksOptions
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.tenancy.impl.manager import TenancyManagerImpl, TenancyOptions
from tadas.om.work import WorkManagerInterface
from tadas.om.work.impl.manager import WorkManagerImpl, WorkOptions


@dataclass(frozen=True)
class Managers:
    tenancy: TenancyManagerInterface
    work: WorkManagerInterface
    tasks: TasksManagerInterface
    idempotency: IdempotencyManagerInterface
    events: EventsManagerInterface


def build_managers(storage: StorageInterface, infra: InfraInterface) -> Managers:
    events = EventsManagerImpl(storage.get_event_storage(), EventsOptions())
    tenancy = TenancyManagerImpl(
        storage.get_tenancy_storage(),
        events,
        infra.get_topics(),
        infra.get_cache(CacheScope.REALTIME_TICKET),
        TenancyOptions(),
    )
    work = WorkManagerImpl(
        storage.get_work_storage(),
        tenancy,
        infra.get_topics(),
        WorkOptions(),
    )
    tasks = TasksManagerImpl(
        storage.get_tasks_storage(),
        events,
        infra.get_topics(),
        TasksOptions(),
    )
    idempotency = IdempotencyManagerImpl(storage.get_idempotency_storage())
    return Managers(tenancy=tenancy, work=work, tasks=tasks, idempotency=idempotency, events=events)
