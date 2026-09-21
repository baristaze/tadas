"""The one socket route and the ticket route that opens it. The gateway
redeems the ticket; the handler subscribes to topics on the client's behalf
through the realtime service, moves frames through the bounded send buffer,
and closes the socket when its authority ends: when the credential behind
the ticket is revoked or the membership ends, which the realtime service
hears on the bus, and at the credential's expiry whatever the client does,
which covers a revocation the bus never delivered."""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
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

CLOSE_INTERNAL_ERROR = 1011
"""The close code for a failure of this handler. The gateway accepted the
socket before the route ran, so there is no HTTP response left to answer
with: an error that reaches Starlette's handler on an accepted socket is
answered with one anyway, which the server refuses as a protocol error and
drops without a close frame. Every failure below ends as this close."""

INTERNAL_ERROR = "internal_error"
"""The close reason that goes with it; the detail stays in the log."""


def new_send_buffer(websocket: WebSocket) -> SendBuffer:
    settings = container_of(websocket).settings
    return SendBuffer(settings.realtime_send_buffer_size, settings.realtime_control_buffer_size)


SocketSendBuffer = Annotated[SendBuffer, Depends(new_send_buffer)]


async def settle(task: asyncio.Task[None]) -> None:
    """Ends a socket's task. One that died because the peer left (a
    disconnect, a closed transport) is the normal end of a socket and not an
    error, and so is one this handler cancelled. Anything else it raised is
    logged and goes no further: `settle` runs in the teardown, and a second
    exception raised from there would skip the unsubscribes and the close
    frame that follow it, leaving the socket's handler in the dispatcher for
    the life of the process."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError, WebSocketDisconnect, OSError:
        return
    except Exception as error:
        log.error("%s ended with %r", task.get_name(), error)


async def close_quietly(websocket: WebSocket, code: int = 1000, reason: str | None = None) -> None:
    """Sends the close frame when there is still a peer to send it to. A peer
    that left first, or a close already sent, is the normal end of a socket:
    the server raises its disconnect error on a send after the peer is gone
    (an `OSError`, which Starlette turns into a 1006 disconnect), and
    Starlette refuses a second close with a `RuntimeError`. None of them
    is an error of this handler."""
    if WebSocketState.DISCONNECTED in (websocket.client_state, websocket.application_state):
        return
    with contextlib.suppress(RuntimeError, WebSocketDisconnect, OSError):
        await websocket.close(code=code, reason=reason)


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
    leaves or stays silent past the idle timeout. A command is a text frame;
    any other frame is a bad command, answered and survived."""
    try:
        while True:
            message = await asyncio.wait_for(websocket.receive(), timeout=IDLE_TIMEOUT_SECONDS)
            if message["type"] == "websocket.disconnect":
                return
            raw = message.get("text")
            if raw is None:
                buffer.offer(ErrorEnvelope(code="bad_command", message="a command is a text frame"))
                continue
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

    # The socket's authority ends with the credential behind its ticket: at
    # its expiry, or at its revocation, the socket is closed with 4401,
    # whatever the client does. It is attached before anything is awaited:
    # the redemption checked the credential, and a revocation that landed
    # during an await before the attach would find no socket to close.
    ended: asyncio.Future[str] = loop.create_future()

    def end(reason: str) -> None:
        if not ended.done():
            ended.set_result(reason)

    detach = realtime.attach(ctx, end)
    # The head is read before the drainer exists: a task created first and a
    # read that raises after it leave the drainer waiting on the buffer for
    # the life of the process, one more on every reconnect through an outage.
    try:
        head = await realtime.head(ctx)
    except Exception:
        detach()
        log.exception("the stream head could not be read for user %s", ctx.user_id)
        await close_quietly(websocket, code=CLOSE_INTERNAL_ERROR, reason=INTERNAL_ERROR)
        return
    drainer = asyncio.create_task(buffer.drain(websocket), name=f"send-buffer-{ctx.user_id}")
    subscriptions: dict[Topics, Callable[[], None]] = {}
    buffer.offer(HelloEnvelope(org_id=ctx.org_id, user_id=ctx.user_id, seq=head))

    remaining = (principal.expires_at - utcnow()).total_seconds()
    expiry = loop.call_later(max(remaining, 0.0), end, CREDENTIAL_EXPIRED)
    commands = asyncio.create_task(
        serve_commands(websocket, ctx, realtime, buffer, subscriptions),
        name=f"commands-{ctx.user_id}",
    )
    # How the socket ends, decided before the teardown and sent after it: the
    # teardown is the only place the subscriptions are dropped, so nothing
    # between here and it may raise past it.
    code: int = 1000
    reason: str | None = None
    try:
        await asyncio.wait({commands, ended}, return_when=asyncio.FIRST_COMPLETED)
        if ended.done():
            code, reason = CLOSE_UNAUTHENTICATED, ended.result()
        elif not commands.cancelled() and (failure := commands.exception()) is not None:
            log.error("%s failed", commands.get_name(), exc_info=failure)
            code, reason = CLOSE_INTERNAL_ERROR, INTERNAL_ERROR
    finally:
        expiry.cancel()
        detach()
        await settle(commands)
        for unsubscribe in subscriptions.values():
            unsubscribe()
        await settle(drainer)
        await close_quietly(websocket, code=code, reason=reason)
