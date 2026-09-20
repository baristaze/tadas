"""The one socket route and the ticket route that opens it. The gateway
redeems the ticket; the handler subscribes to topics on the client's behalf
through the realtime service, moves frames through the bounded send buffer,
and closes the socket when its authority ends: at the expiry of the
credential behind the ticket, whatever the client does."""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from tadas.infra.topics import Topics
from tadas.om.base import utcnow
from tadas.om.exceptions import PlatformException
from tadas.om.opcontext import OpContext
from tadas.services.api.gateway.auth import CLOSE_UNAUTHENTICATED, Ctx, Principal
from tadas.services.api.gateway.resolve import RealtimeService, container_of
from tadas.services.api.realtime.envelopes import (
    ClientCommand,
    ErrorEnvelope,
    HelloEnvelope,
    IssuedTicketView,
    PongEnvelope,
    SubscribedEnvelope,
    UnsubscribedEnvelope,
)
from tadas.services.api.realtime.send_buffer import SendBuffer
from tadas.services.api.realtime.timeouts import IDLE_TIMEOUT_SECONDS
from tadas.services.api.services.realtime import RealtimeServiceInterface

log = logging.getLogger(__name__)
router = APIRouter(prefix="/realtime", tags=["realtime"])

CREDENTIAL_EXPIRED = "credential_expired"
"""The close reason when the credential behind the ticket reached its expiry."""


def new_send_buffer(websocket: WebSocket) -> SendBuffer:
    return SendBuffer(container_of(websocket).settings.realtime_send_buffer_size)


SocketSendBuffer = Annotated[SendBuffer, Depends(new_send_buffer)]


async def settle(task: asyncio.Task[None]) -> None:
    """Ends a socket's task. One that died because the peer left (a
    disconnect, a closed transport) is the normal end of a socket and not an
    error, and so is one this handler cancelled; anything else it raised
    propagates."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, OSError):
        await task


@router.post("/tickets", response_model=IssuedTicketView, status_code=201)
async def mint_ticket(ctx: Ctx, realtime: RealtimeService) -> IssuedTicketView:
    return await realtime.issue_ticket(ctx)


async def serve_commands(
    websocket: WebSocket,
    ctx: OpContext,
    realtime: RealtimeServiceInterface,
    buffer: SendBuffer,
    subscriptions: dict[Topics, Callable[[], None]],
) -> None:
    """The inbound loop: subscribe, unsubscribe, ping. Returns when the peer
    leaves or stays silent past the idle timeout."""
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
        return


@router.websocket("")
async def channel(
    websocket: WebSocket, principal: Principal, realtime: RealtimeService, buffer: SocketSendBuffer
) -> None:
    # The gateway accepted the socket before it redeemed the ticket.
    ctx = principal.ctx
    loop = asyncio.get_running_loop()
    drainer = asyncio.create_task(buffer.drain(websocket), name=f"send-buffer-{ctx.user_id}")
    subscriptions: dict[Topics, Callable[[], None]] = {}
    buffer.offer(
        HelloEnvelope(org_id=ctx.org_id, user_id=ctx.user_id, seq=await realtime.head(ctx))
    )

    # The socket's authority ends with the credential behind its ticket: at
    # its expiry the socket is closed with 4401, whatever the client does.
    ended: asyncio.Future[str] = loop.create_future()

    def end(reason: str) -> None:
        if not ended.done():
            ended.set_result(reason)

    remaining = (principal.expires_at - utcnow()).total_seconds()
    expiry = loop.call_later(max(remaining, 0.0), end, CREDENTIAL_EXPIRED)
    commands = asyncio.create_task(
        serve_commands(websocket, ctx, realtime, buffer, subscriptions),
        name=f"commands-{ctx.user_id}",
    )
    try:
        await asyncio.wait({commands, ended}, return_when=asyncio.FIRST_COMPLETED)
        if ended.done():
            await settle(commands)
            await settle(drainer)
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=CLOSE_UNAUTHENTICATED, reason=ended.result())
        else:
            commands.result()
    finally:
        expiry.cancel()
        await settle(commands)
        for unsubscribe in subscriptions.values():
            unsubscribe()
        await settle(drainer)
        with contextlib.suppress(RuntimeError):
            await websocket.close()
