"""The realtime service: mints the ticket that opens the channel and forwards
the tenant's pushes on it as typed envelopes. The gateway redeems the ticket;
the socket handler moves frames."""

from collections.abc import Callable

from tadas.infra.topics import Topics
from tadas.om.opcontext import OpContext
from tadas.services.api.realtime.envelopes import EventEnvelope, TicketView


class RealtimeServiceInterface:
    async def issue_ticket(self, ctx: OpContext) -> TicketView: ...

    def subscribe(
        self, ctx: OpContext, topic: Topics, deliver: Callable[[EventEnvelope], None]
    ) -> Callable[[], None]:
        """Hands `deliver` every push on `topic` for the caller's tenant, projected
        onto its view; returns the unsubscribe callable. Raises ValidationFailed
        for a topic the channel does not carry."""
        ...
