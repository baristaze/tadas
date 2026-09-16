"""Every frame on the socket is a typed envelope; the client routes on `type`.
Inbound traffic is small by design: subscribe, unsubscribe, ping."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from tadas.services.api.types.common import RequestBody, View

PING_INTERVAL_SECONDS = 25
"""Pinned with the load balancer idle timeout in deployment/realtime-timeouts.json."""

IDLE_TIMEOUT_SECONDS = PING_INTERVAL_SECONDS * 3


class Envelope(View):
    """Subclasses declare `type` as a literal; the client routes on it."""

    seq: int = 0
    sent_at: datetime | None = None


class HelloEnvelope(Envelope):
    type: Literal["hello"] = "hello"
    org_id: UUID
    user_id: UUID
    ping_interval_seconds: int = PING_INTERVAL_SECONDS


class PongEnvelope(Envelope):
    type: Literal["pong"] = "pong"


class SubscribedEnvelope(Envelope):
    type: Literal["subscribed"] = "subscribed"
    topic: str


class UnsubscribedEnvelope(Envelope):
    type: Literal["unsubscribed"] = "unsubscribed"
    topic: str


class EventEnvelope(Envelope):
    type: Literal["event"] = "event"
    topic: str
    payload: dict[str, Any]


class ErrorEnvelope(Envelope):
    type: Literal["error"] = "error"
    code: str
    message: str


class ClientCommand(RequestBody):
    op: Literal["subscribe", "unsubscribe", "ping"]
    topic: str | None = None


class TicketView(View):
    ticket: str
    expires_in_seconds: int
