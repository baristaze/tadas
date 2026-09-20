"""The realtime service: mints the ticket that opens the channel and forwards
the tenant's pushes on it as typed envelopes. The gateway redeems the ticket;
the socket handler moves frames."""

from abc import ABC, abstractmethod
from collections.abc import Callable

from tadas.infra.topics import Topics
from tadas.om.opcontext import ActorScope, OpContext
from tadas.services.api.realtime.envelopes import EventEnvelope, IssuedTicketView


class RealtimeServiceInterface(ABC):
    @abstractmethod
    async def issue_ticket(self, ctx: OpContext) -> IssuedTicketView: ...

    @abstractmethod
    async def head(self, ctx: OpContext) -> int:
        """The tenant's stream position when a socket opens; the hello carries it
        so a client can replay from there before it has seen any push."""
        ...

    @abstractmethod
    def subscribe(
        self, ctx: ActorScope, topic: Topics, deliver: Callable[[EventEnvelope], None]
    ) -> Callable[[], None]:
        """Hands `deliver` every push on `topic` for the caller's tenant, projected
        onto its view; returns the unsubscribe callable. Raises ValidationFailed
        for a topic the channel does not carry. Reads the tenant and the user
        and nothing else; `head` and `issue_ticket` keep `OpContext` because
        the managers behind them authorize."""
        ...
