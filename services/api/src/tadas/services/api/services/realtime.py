"""The realtime service: mints the ticket that opens the channel, forwards
the tenant's pushes on it as typed envelopes, and ends the sockets a
revocation names. The gateway redeems the ticket; the socket handler moves
frames and closes when told to."""

from abc import ABC, abstractmethod
from collections.abc import Callable

from tadas.infra.topics import Topics
from tadas.om.opcontext import ActorScope, OpContext
from tadas.services.api.realtime.envelopes import EventEnvelope, IssuedTicketView

CREDENTIAL_REVOKED = "credential_revoked"
"""The close reason when the session or the api key behind the socket was revoked."""

MEMBERSHIP_ENDED = "membership_ended"
"""The close reason when the user behind the socket was removed from the tenant."""


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

    @abstractmethod
    def attach(self, ctx: OpContext, end: Callable[[str], None]) -> Callable[[], None]:
        """Registers an open socket under the principal its ticket produced.
        `end` is called, on the event loop, with the close reason when the
        session or the api key behind the socket is revoked or the user's
        membership ends, in whichever process the revocation happened: the
        service hears every change on the bus. Returns the detach callable."""
        ...
