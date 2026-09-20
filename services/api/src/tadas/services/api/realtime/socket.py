"""The one socket route and the ticket route that opens it. The gateway
redeems the ticket; the handler subscribes to topics on the client's behalf
through the realtime service and moves frames through the bounded send buffer."""

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
    IssuedTicketView,
    PongEnvelope,
    SubscribedEnvelope,
    UnsubscribedEnvelope,
)
from tadas.services.api.realtime.send_buffer import SendBuffer

log = logging.getLogger(__name__)
router = APIRouter(prefix="/realtime", tags=["realtime"])


def new_send_buffer(websocket: WebSocket) -> SendBuffer:
    return SendBuffer(container_of(websocket).settings.realtime_send_buffer_size)


SocketSendBuffer = Annotated[SendBuffer, Depends(new_send_buffer)]


@router.post("/tickets", response_model=IssuedTicketView, status_code=201)
async def mint_ticket(ctx: Ctx, realtime: RealtimeService) -> IssuedTicketView:
    return await realtime.issue_ticket(ctx)


@router.websocket("")
async def channel(
    websocket: WebSocket, ctx: SocketCtx, realtime: RealtimeService, buffer: SocketSendBuffer
) -> None:
    await websocket.accept()
    drainer = asyncio.create_task(buffer.drain(websocket), name=f"send-buffer-{ctx.user_id}")
    subscriptions: dict[Topics, Callable[[], None]] = {}
    buffer.offer(
        HelloEnvelope(org_id=ctx.org_id, user_id=ctx.user_id, seq=await realtime.head(ctx))
    )

    try:
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=IDLE_TIMEOUT_SECONDS)
            try:
                command = ClientCommand.model_validate_json(raw)
                topic = Topics(command.topic) if command.topic is not None else None
            except (ValidationError, ValueError) as error:
                buffer.offer(ErrorEnvelope(code="bad_command", message=str(error)[:200]))
                continue
            if command.op == "ping":
                buffer.offer(PongEnvelope(seq=await realtime.head(ctx)))
            elif topic is None:
                buffer.offer(ErrorEnvelope(code="bad_command", message="topic is required"))
            elif command.op == "subscribe":
                if topic not in subscriptions:
                    try:
                        subscriptions[topic] = realtime.subscribe(ctx, topic, buffer.offer)
                    except PlatformException as error:
                        buffer.offer(ErrorEnvelope(code=error.code, message=error.message))
                        continue
                buffer.offer(SubscribedEnvelope(topic=topic.value))
            else:
                if (unsubscribe := subscriptions.pop(topic, None)) is not None:
                    unsubscribe()
                buffer.offer(UnsubscribedEnvelope(topic=topic.value))
    except WebSocketDisconnect, TimeoutError:
        pass
    finally:
        for unsubscribe in subscriptions.values():
            unsubscribe()
        drainer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await drainer
        with contextlib.suppress(RuntimeError):
            await websocket.close()
