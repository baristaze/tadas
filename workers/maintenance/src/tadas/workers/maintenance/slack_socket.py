"""The Socket Mode bridge: the one process that holds Slack's connection.

Slack's commands and events arrive over a websocket the app opens with its
app token, not over HTTP, and Slack wants each one acknowledged within three
seconds. So the bridge does two things per delivery, in this order: it
acknowledges on the socket, and then it puts the delivery on the `slack`
queue for a worker. Nothing is looked up, parsed, or decided before the
acknowledgement, so a slow database or a slow queue can never make Slack
retry.

Slack retries what it did not see acknowledged, and it spreads deliveries
across every open connection of the app. One process per environment holds
the connection, so a delivery it already queued is remembered here, in
memory, by its key, and a retry is acknowledged and dropped. The queue is at
least once all the same, and the worker's handling is idempotent on the same
key.

The connection opens only when an app token is set. Local and staging share
one Slack app, and a laptop holding a connection would take staging's
deliveries, so a developer's `.env` leaves the token empty."""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Protocol

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from tadas.infra.observability import OUTCOMES
from tadas.infra.queues import Queues, QueuesInterface
from tadas.om.base import utcnow
from tadas.workers.maintenance.slack_inbound import InboundDelivery, delivery_key

log = logging.getLogger(__name__)

REMEMBERED = 2048
"""How many recent delivery keys the bridge keeps to drop Slack's retries.
Slack retries within minutes; this is far more deliveries than that."""


class SocketRequest(Protocol):
    """What the bridge reads off a Socket Mode request."""

    @property
    def envelope_id(self) -> str: ...

    @property
    def type(self) -> str: ...

    @property
    def payload(self) -> dict[str, Any]: ...


Ack = Callable[[str], Awaitable[None]]
"""Sends the acknowledgement of one envelope back on the socket."""


class SlackSocketBridge:
    def __init__(self, queues: QueuesInterface) -> None:
        self._queues = queues
        self._seen: OrderedDict[str, None] = OrderedDict()

    async def on_request(self, ack: Ack, request: SocketRequest) -> None:
        """Acknowledge, then queue. The acknowledgement goes back before
        anything else happens, whatever follows it."""
        await ack(request.envelope_id)
        OUTCOMES.labels(subsystem="slack_socket", outcome="acknowledged").inc()
        payload = dict(request.payload or {})
        key = delivery_key(request.type, request.envelope_id, payload)
        if str(key) in self._seen:
            OUTCOMES.labels(subsystem="slack_socket", outcome="duplicate").inc()
            log.info("slack delivery %s is a retry; dropped", key)
            return
        delivery = InboundDelivery(
            key=key, received_at=utcnow(), type=request.type, payload=payload
        )
        try:
            await self._queues.send(Queues.SLACK, delivery.model_dump_json().encode())
        except Exception:
            # Acknowledged and not queued: Slack will not send it again, so the
            # delivery is lost, and the log and the counter say so.
            log.exception("slack delivery %s was acknowledged and could not be queued", key)
            OUTCOMES.labels(subsystem="slack_socket", outcome="lost").inc()
            return
        self._remember(str(key))
        OUTCOMES.labels(subsystem="slack_socket", outcome="queued").inc()

    def _remember(self, key: str) -> None:
        self._seen[key] = None
        while len(self._seen) > REMEMBERED:
            self._seen.popitem(last=False)


async def hold_connection(
    app_token: str, bridge: SlackSocketBridge, stopping: asyncio.Event, bound: timedelta
) -> None:
    """Opens the Socket Mode connection and holds it until `stopping` is set.
    The client reconnects on its own when Slack cycles the socket; opening it
    is bounded by `bound`, and so is the call that asks Slack for the
    socket's address."""
    seconds = int(bound.total_seconds())
    client = SocketModeClient(
        app_token=app_token, web_client=AsyncWebClient(timeout=seconds), ping_interval=10
    )

    async def listener(socket: SocketModeClient, request: SocketModeRequest) -> None:
        async def ack(envelope_id: str) -> None:
            await socket.send_socket_mode_response(SocketModeResponse(envelope_id=envelope_id))

        await bridge.on_request(ack, request)

    client.socket_mode_request_listeners.append(listener)  # type: ignore[arg-type]
    await asyncio.wait_for(client.connect(), timeout=bound.total_seconds())
    log.info("slack socket mode connection is open")
    try:
        await stopping.wait()
    finally:
        await client.close()
        log.info("slack socket mode connection is closed")
