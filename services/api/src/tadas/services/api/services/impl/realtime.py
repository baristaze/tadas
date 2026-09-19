from collections.abc import Callable

from tadas.infra.topics import TopicPayload, Topics, TopicsInterface
from tadas.om.base import utcnow
from tadas.om.events import EventsManagerInterface
from tadas.om.exceptions import ValidationFailed
from tadas.om.opcontext import ActorScope, OpContext
from tadas.om.tenancy import TenancyManagerInterface
from tadas.services.api.realtime.envelopes import EventEnvelope, TicketView
from tadas.services.api.services.realtime import RealtimeServiceInterface
from tadas.services.api.types.events import EntityChangedView

PROJECTIONS: dict[Topics, Callable[[TopicPayload], EntityChangedView]] = {
    Topics.ENTITY_CHANGED: EntityChangedView.model_validate,
}
"""The topics the channel carries, each with the view its payload is projected
onto before a frame is offered. A topic outside this map never reaches a client."""


class RealtimeServiceImpl(RealtimeServiceInterface):
    def __init__(
        self,
        tenancy: TenancyManagerInterface,
        events: EventsManagerInterface,
        topics: TopicsInterface,
    ) -> None:
        self._tenancy = tenancy
        self._events = events
        self._topics = topics

    async def head(self, ctx: OpContext) -> int:
        return await self._events.get_head(ctx)

    async def issue_ticket(self, ctx: OpContext) -> TicketView:
        issued = await self._tenancy.issue_ticket(ctx)
        remaining = int((issued.expires_at - utcnow()).total_seconds())
        return TicketView(ticket=issued.ticket, expires_in_seconds=max(remaining, 0))

    def subscribe(
        self, ctx: ActorScope, topic: Topics, deliver: Callable[[EventEnvelope], None]
    ) -> Callable[[], None]:
        project = PROJECTIONS.get(topic)
        if project is None:
            raise ValidationFailed(f"topic {topic.value!r} is not carried on the channel")

        async def forward(payload: TopicPayload) -> None:
            if payload.org_id == ctx.org_id:
                deliver(EventEnvelope(topic=topic.value, payload=project(payload)))

        return self._topics.subscribe(topic, f"socket:{ctx.user_id}", forward)
