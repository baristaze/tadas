from tadas.om.events import EventsManagerInterface
from tadas.om.opcontext import OpContext
from tadas.services.api.services.events import EventsServiceInterface
from tadas.services.api.types.common import clamp_limit
from tadas.services.api.types.events import EventView


class EventsServiceImpl(EventsServiceInterface):
    def __init__(self, events: EventsManagerInterface) -> None:
        self._events = events

    async def get_events(self, ctx: OpContext, after_seq: int, limit: int) -> list[EventView]:
        events = await self._events.get_events(ctx, after_seq, clamp_limit(limit))
        return [EventView.model_validate(e) for e in events]
