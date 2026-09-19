"""The one channel: a socket opened on a single-use ticket, one subscription
to `entity_changed`, pings at the interval the hello names, and an async
iterator of changes in stream order. A push ahead of the cursor is a replay
of `/v1/events` after it, never a skip; a dropped socket reconnects with
backoff and replays the same way, so a consumer sees every change once."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Literal, Protocol

import websockets

from tadas.client.client import LIMIT_MAX, ApiClient, trust_store
from tadas.client.envelopes import (
    ENTITY_CHANGED,
    PING_COMMAND,
    EntityChanged,
    ErrorEnvelope,
    EventEnvelope,
    HelloEnvelope,
    parse_envelope,
    subscribe_command,
)
from tadas.client.stream import Cursor, Gap, Next, Seen, is_last_page, place

log = logging.getLogger(__name__)

SOCKET_PATH = "/v1/realtime"
BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
MIN_PING_SECONDS = 1.0  # a hello that names less would spin
CLOSE_UNAUTHENTICATED = 4401

State = Literal["connecting", "open", "reconnecting", "closed"]


class SocketLike(Protocol):
    """What the channel needs of a socket; `ClientConnection` is one, a test double another."""

    async def recv(self) -> str | bytes: ...

    async def send(self, message: str) -> None: ...


Connect = Callable[[str, dict[str, str]], AbstractAsyncContextManager[SocketLike]]
"""Opens the socket at a URL with the app headers; injected by tests."""


class ChannelRefused(Exception):
    """The socket closed with 4401: the credential behind the ticket is gone.
    Reconnecting would not help; the consumer signs in again."""


class Channel:
    """`async for change in Channel(client)`. `on_state` hears every transition."""

    def __init__(
        self,
        client: ApiClient,
        *,
        on_state: Callable[[State], None] | None = None,
        connect: Connect | None = None,
    ) -> None:
        self._client = client
        self._on_state = on_state or (lambda _: None)
        self._connect = connect or self._connect_default
        self.cursor: Cursor = None
        self.state: State = "closed"

    def _connect_default(
        self, url: str, headers: dict[str, str]
    ) -> AbstractAsyncContextManager[SocketLike]:
        ssl_context = trust_store() if url.startswith("wss") else None
        return websockets.connect(url, additional_headers=headers, ssl=ssl_context, max_size=None)

    def _set(self, state: State) -> None:
        if state != self.state:
            self.state = state
            self._on_state(state)

    async def __aiter__(self) -> AsyncIterator[EntityChanged]:
        attempt = 0
        while True:
            self._set("connecting" if attempt == 0 else "reconnecting")
            try:
                async for change in self._session():
                    attempt = 0
                    yield change
            except ChannelRefused:
                self._set("closed")
                raise
            except (OSError, websockets.exceptions.WebSocketException, TimeoutError) as error:
                log.info("channel dropped: %s", error)
            delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            attempt += 1
            self._set("reconnecting")
            await asyncio.sleep(delay)

    async def _session(self) -> AsyncIterator[EntityChanged]:
        ticket = await self._client.ticket()
        url = f"{self._client.websocket_url(SOCKET_PATH)}?ticket={ticket.ticket}"
        try:
            async with self._connect(url, self._client.headers) as socket:
                hello = parse_envelope(await socket.recv())
                if not isinstance(hello, HelloEnvelope):
                    raise websockets.exceptions.ProtocolError("expected hello")
                await socket.send(subscribe_command(ENTITY_CHANGED))
                self._set("open")
                # Anything that happened while the socket was down.
                if self.cursor is not None:
                    async for change in self._replay(self.cursor):
                        yield change
                interval = max(float(hello.ping_interval_seconds), MIN_PING_SECONDS)
                async for change in self._frames(socket, interval):
                    yield change
        except websockets.exceptions.ConnectionClosed as closed:
            if closed.rcvd is not None and closed.rcvd.code == CLOSE_UNAUTHENTICATED:
                raise ChannelRefused(closed.rcvd.reason) from None
            raise

    async def _frames(self, socket: SocketLike, interval: float) -> AsyncIterator[EntityChanged]:
        while True:
            try:
                raw = await asyncio.wait_for(socket.recv(), timeout=interval)
            except TimeoutError:
                await socket.send(PING_COMMAND)
                continue
            envelope = parse_envelope(raw)
            if isinstance(envelope, ErrorEnvelope):
                log.warning("channel error %s: %s", envelope.code, envelope.message)
            if not isinstance(envelope, EventEnvelope) or envelope.topic != ENTITY_CHANGED:
                continue
            match place(self.cursor, envelope.payload.seq):
                case Next(cursor=cursor):
                    self.cursor = cursor
                    yield envelope.payload
                case Seen():
                    continue
                case Gap(after=after):
                    async for change in self._replay(after):
                        yield change
                    # The frame itself is behind or at the cursor now, or the
                    # replay ended short of it and the next replay catches up.
                    if place(self.cursor, envelope.payload.seq).kind == "next":
                        self.cursor = envelope.payload.seq
                        yield envelope.payload

    async def _replay(self, after: int) -> AsyncIterator[EntityChanged]:
        """Every record after `after`, page by page, in order; the cursor
        follows each one so a crash mid-replay resumes where it stopped."""
        while True:
            events = await self._client.events_after(after, LIMIT_MAX)
            for event in events:
                if place(self.cursor, event.seq).kind == "next":
                    self.cursor = event.seq
                    yield EntityChanged.of_event(event)
            if not events or is_last_page(len(events), LIMIT_MAX):
                return
            after = events[-1].seq
