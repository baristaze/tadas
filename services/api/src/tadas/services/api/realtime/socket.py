"""The one socket route and the ticket route that opens it. The handler
subscribes to topics on the client's behalf, filters by tenant, and moves
frames through the bounded outbox."""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from tadas.infra.cache import CacheScope
from tadas.infra.topics import TopicPayload, Topics
from tadas.om.exceptions import PlatformException
from tadas.services.api.container import AppContainer
from tadas.services.api.gateway.auth import Ctx, app_context_of
from tadas.services.api.gateway.observability import request_id_of
from tadas.services.api.realtime.envelopes import (
    IDLE_TIMEOUT_SECONDS,
    ClientCommand,
    ErrorEnvelope,
    EventEnvelope,
    HelloEnvelope,
    PongEnvelope,
    SubscribedEnvelope,
    TicketView,
    UnsubscribedEnvelope,
)
from tadas.services.api.realtime.outbox import Outbox
from tadas.services.api.realtime.ticket import TicketStore

log = logging.getLogger(__name__)
router = APIRouter(prefix="/realtime", tags=["realtime"])

CLOSE_UNAUTHENTICATED = 4401


def _tickets(container: AppContainer) -> TicketStore:
    return TicketStore(
        container.infra.get_cache(CacheScope.REALTIME_TICKET),
        timedelta(seconds=container.settings.realtime_ticket_ttl_seconds),
    )


@router.post("/tickets", response_model=TicketView, status_code=201)
async def mint_ticket(request: Request, ctx: Ctx) -> TicketView:
    container: AppContainer = request.app.state.container
    ticket = await _tickets(container).mint(ctx)
    return TicketView(
        ticket=ticket, expires_in_seconds=container.settings.realtime_ticket_ttl_seconds
    )


@router.websocket("")
async def realtime(
    websocket: WebSocket,
    ticket: Annotated[str, Query()],
    x_app: Annotated[str | None, Header()] = None,
    x_app_version: Annotated[str | None, Header()] = None,
) -> None:
    container: AppContainer = websocket.app.state.container
    try:
        org_id, kind, credential_id = await _tickets(container).redeem(ticket)
        ctx = await container.managers.tenancy.resume(
            org_id,
            kind,
            credential_id,
            app_context_of(x_app, x_app_version),
            request_id_of(websocket.scope),
        )
    except PlatformException as error:
        log.info("socket refused: %s", error.message)
        await websocket.close(code=CLOSE_UNAUTHENTICATED, reason=error.code)
        return

    await websocket.accept()
    outbox = Outbox(container.settings.realtime_outbox_size)
    drainer = asyncio.create_task(outbox.drain(websocket), name=f"outbox-{ctx.user_id}")
    subscriptions: dict[Topics, Callable[[], None]] = {}
    topics = container.infra.get_topics()
    outbox.offer(HelloEnvelope(org_id=ctx.org_id, user_id=ctx.user_id))

    def subscribe(topic: Topics) -> None:
        async def forward(payload: TopicPayload) -> None:
            if payload.org_id == ctx.org_id:
                outbox.offer(
                    EventEnvelope(topic=topic.value, payload=payload.model_dump(mode="json"))
                )

        if topic not in subscriptions:
            subscriptions[topic] = topics.subscribe(topic, f"socket:{ctx.user_id}", forward)
        outbox.offer(SubscribedEnvelope(topic=topic.value))

    try:
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=IDLE_TIMEOUT_SECONDS)
            try:
                command = ClientCommand.model_validate_json(raw)
                topic = Topics(command.topic) if command.topic is not None else None
            except (ValidationError, ValueError) as error:
                outbox.offer(ErrorEnvelope(code="bad_command", message=str(error)[:200]))
                continue
            if command.op == "ping":
                outbox.offer(PongEnvelope())
            elif topic is None:
                outbox.offer(ErrorEnvelope(code="bad_command", message="topic is required"))
            elif command.op == "subscribe":
                subscribe(topic)
            else:
                if (unsubscribe := subscriptions.pop(topic, None)) is not None:
                    unsubscribe()
                outbox.offer(UnsubscribedEnvelope(topic=topic.value))
    except (WebSocketDisconnect, TimeoutError):
        pass
    finally:
        for unsubscribe in subscriptions.values():
            unsubscribe()
        drainer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await drainer
        with contextlib.suppress(RuntimeError):
            await websocket.close()
