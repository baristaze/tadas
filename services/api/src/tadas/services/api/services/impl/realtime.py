import itertools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from tadas.infra.topics import EntityChangedPayload, TopicPayload, Topics, TopicsInterface
from tadas.om.base import utcnow
from tadas.om.events import EventsManagerInterface
from tadas.om.exceptions import NotAuthenticated, ValidationFailed
from tadas.om.opcontext import ActorScope, OpContext
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.tenancy.types.socket_ticket import SocketPrincipal
from tadas.services.api.realtime.envelopes import EventEnvelope, IssuedTicketView
from tadas.services.api.services.realtime import (
    CREDENTIAL_REVOKED,
    MEMBERSHIP_ENDED,
    RIGHTS_CHANGED,
    RealtimeServiceInterface,
)
from tadas.services.api.types.events import EntityChangedView

PROJECTIONS: dict[Topics, Callable[[TopicPayload], EntityChangedView]] = {
    Topics.ENTITY_CHANGED: EntityChangedView.model_validate,
}
"""The topics the channel carries, each with the view its payload is projected
onto before a frame is offered. A topic outside this map never reaches a client."""

REVOCATIONS: dict[str, tuple[Literal["credential", "user", "membership", "org"], str]] = {
    "tenancy.session.revoked": ("credential", CREDENTIAL_REVOKED),
    "tenancy.api_key.deleted": ("credential", CREDENTIAL_REVOKED),
    "tenancy.user.deleted": ("user", MEMBERSHIP_ENDED),
    "tenancy.membership.updated": ("membership", RIGHTS_CHANGED),
    "tenancy.org.deleted": ("org", MEMBERSHIP_ENDED),
}
"""The change kinds that end a socket: which id of the socket the target
names (the credential behind its ticket, its user, the membership its
context was built from, or its org, whose deletion ends every membership in
it) and the close reason. A membership's change is a change of its role, so
the socket closes to be opened again under the role the member has now."""


@dataclass(frozen=True)
class AttachedSocket:
    org_id: UUID
    user_id: UUID
    credential_id: UUID
    membership_id: UUID
    end: Callable[[str], None]


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
        self._ids = itertools.count()
        self._sockets: dict[int, AttachedSocket] = {}
        # One subscription per process: every replica hears every revocation
        # and ends the sockets it holds for it, as it does for every push.
        self._topics.subscribe(Topics.ENTITY_CHANGED, "socket-revocations", self._on_change)

    async def head(self, ctx: OpContext) -> int:
        return await self._events.get_head(ctx)

    async def recheck(self, principal: SocketPrincipal) -> str | None:
        ctx = principal.ctx
        # The socket is a request that stays open: its recheck runs under the
        # request stage of the handshake that opened it, which its context
        # carries.
        try:
            current = await self._tenancy.resume(
                ctx, ctx.org_id, principal.credential_kind, ctx.credential_id, record_use=False
            )
        except NotAuthenticated as refused:
            return refused.code
        if current.ctx.security != ctx.security:
            return RIGHTS_CHANGED
        return None

    async def issue_ticket(self, ctx: OpContext) -> IssuedTicketView:
        issued = await self._tenancy.issue_ticket(ctx)
        remaining = int((issued.expires_at - utcnow()).total_seconds())
        return IssuedTicketView(ticket=issued.ticket, expires_in_seconds=max(remaining, 0))

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

    def attach(self, principal: SocketPrincipal, end: Callable[[str], None]) -> Callable[[], None]:
        ctx = principal.ctx
        socket_id = next(self._ids)
        self._sockets[socket_id] = AttachedSocket(
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            credential_id=ctx.credential_id,
            membership_id=principal.membership_id,
            end=end,
        )

        def detach() -> None:
            self._sockets.pop(socket_id, None)

        return detach

    async def _on_change(self, payload: TopicPayload) -> None:
        if not isinstance(payload, EntityChangedPayload):
            return
        revocation = REVOCATIONS.get(payload.kind)
        if revocation is None:
            return
        subject, reason = revocation
        for attached in list(self._sockets.values()):
            if attached.org_id != payload.org_id:
                continue
            named = {
                "credential": attached.credential_id,
                "user": attached.user_id,
                "membership": attached.membership_id,
                "org": attached.org_id,
            }[subject]
            if named == payload.target_id:
                attached.end(reason)
