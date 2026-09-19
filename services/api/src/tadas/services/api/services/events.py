"""The events service: the tenant's append-only stream, paged by `after_seq`."""

from abc import ABC, abstractmethod

from tadas.om.opcontext import OpContext
from tadas.services.api.types.events import EventView


class EventsServiceInterface(ABC):
    @abstractmethod
    async def get_events(self, ctx: OpContext, after_seq: int, limit: int) -> list[EventView]: ...
