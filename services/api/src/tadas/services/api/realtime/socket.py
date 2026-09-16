"""The one socket route and the ticket route that opens it. The gateway
redeems the ticket; the handler subscribes to topics on the client's behalf
through the realtime service and moves frames through the bounded outbox."""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from tadas.infra.topics import Topics
from tadas.om.exceptions import PlatformException
from tadas.services.api.gateway.auth import Ctx, SocketCtx
from tadas.services.api.gateway.resolve import RealtimeService, container_of
from tadas.services.api.realtime.envelopes import (
    IDLE_TIMEOUT_SECONDS,
    ClientCommand,
    ErrorEnvelope,
    HelloEnvelope,
    PongEnvelope,
    SubscribedEnvelope,
    TicketView,
    UnsubscribedEnvelope,
)
from tadas.services.api.realtime.outbox import Outbox

log = logging.getLogger(__name__)
router = APIRouter(prefix="/realtime", tags=["realtime"])


def new_outbox(websocket: WebSocket) -> Outbox:
    return Outbox(container_of(websocket).settings.realtime_outbox_size)


SocketOutbox = Annotated[Outbox, Depends(new_outbox)]


@router.post("/tickets", response_model=TicketView, status_code=201)
async def mint_ticket(ctx: Ctx, realtime: RealtimeService) -> TicketView:
    return await realtime.issue_ticket(ctx)


@router.websocket("")
async def channel(
    websocket: WebSocket, ctx: SocketCtx, realtime: RealtimeService, outbox: SocketOutbox
) -> None:
    await websocket.accept()
    drainer = asyncio.create_task(outbox.drain(websocket), name=f"outbox-{ctx.user_id}")
    subscriptions: dict[Topics, Callable[[], None]] = {}
    outbox.offer(HelloEnvelope(org_id=ctx.org_id, user_id=ctx.user_id))

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
                if topic not in subscriptions:
                    try:
                        subscriptions[topic] = realtime.subscribe(ctx, topic, outbox.offer)
                    except PlatformException as error:
                        outbox.offer(ErrorEnvelope(code=error.code, message=error.message))
                        continue
                outbox.offer(SubscribedEnvelope(topic=topic.value))
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
