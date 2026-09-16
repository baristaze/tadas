"""The network-layer root: one getter per service. A router resolves the
service it needs from this object and makes one call into it; the impl
translates the request, calls one manager, and projects the result."""

from tadas.services.api.services.admin import AdminServiceInterface
from tadas.services.api.services.events import EventsServiceInterface
from tadas.services.api.services.realtime import RealtimeServiceInterface
from tadas.services.api.services.tasks import TasksServiceInterface
from tadas.services.api.services.tenancy import TenancyServiceInterface

__all__ = [
    "AdminServiceInterface",
    "EventsServiceInterface",
    "RealtimeServiceInterface",
    "ServicesInterface",
    "TasksServiceInterface",
    "TenancyServiceInterface",
]


class ServicesInterface:
    def get_tasks_service(self) -> TasksServiceInterface: ...

    def get_tenancy_service(self) -> TenancyServiceInterface: ...

    def get_admin_service(self) -> AdminServiceInterface: ...

    def get_events_service(self) -> EventsServiceInterface: ...

    def get_realtime_service(self) -> RealtimeServiceInterface: ...
