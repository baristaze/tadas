"""Composes one service impl per hosted namespace over the managers and
hands back the network-layer root the container holds."""

from tadas.infra.root import InfraInterface
from tadas.om.root import Managers
from tadas.services.api.services import (
    AdminServiceInterface,
    EventsServiceInterface,
    RealtimeServiceInterface,
    ServicesInterface,
    SlackServiceInterface,
    TasksServiceInterface,
    TenancyServiceInterface,
)
from tadas.services.api.services.impl.admin import AdminServiceImpl
from tadas.services.api.services.impl.events import EventsServiceImpl
from tadas.services.api.services.impl.realtime import RealtimeServiceImpl
from tadas.services.api.services.impl.slack import SlackServiceImpl
from tadas.services.api.services.impl.tasks import TasksServiceImpl
from tadas.services.api.services.impl.tenancy import TenancyServiceImpl


class ServicesImpl(ServicesInterface):
    def __init__(
        self,
        tasks: TasksServiceInterface,
        tenancy: TenancyServiceInterface,
        admin: AdminServiceInterface,
        events: EventsServiceInterface,
        realtime: RealtimeServiceInterface,
        slack: SlackServiceInterface,
    ) -> None:
        self._tasks = tasks
        self._tenancy = tenancy
        self._admin = admin
        self._events = events
        self._realtime = realtime
        self._slack = slack

    def get_tasks_service(self) -> TasksServiceInterface:
        return self._tasks

    def get_tenancy_service(self) -> TenancyServiceInterface:
        return self._tenancy

    def get_admin_service(self) -> AdminServiceInterface:
        return self._admin

    def get_events_service(self) -> EventsServiceInterface:
        return self._events

    def get_realtime_service(self) -> RealtimeServiceInterface:
        return self._realtime

    def get_slack_service(self) -> SlackServiceInterface:
        return self._slack


def build_services(managers: Managers, infra: InfraInterface) -> ServicesInterface:
    """In-process impls only: the remote impl of each interface is the typed
    Python client, which arrives with the first Python consumer (ADR 0004)."""
    return ServicesImpl(
        tasks=TasksServiceImpl(managers.tasks),
        tenancy=TenancyServiceImpl(managers.tenancy),
        admin=AdminServiceImpl(managers.tenancy_operator),
        events=EventsServiceImpl(managers.events),
        realtime=RealtimeServiceImpl(managers.tenancy, managers.events, infra.get_topics()),
        slack=SlackServiceImpl(managers.slack),
    )
