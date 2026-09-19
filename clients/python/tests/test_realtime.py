"""The channel over a fake socket: order, gaps replayed from the stream,
reconnects that replay after the cursor, silence answered with a ping, and a
refused ticket that stops."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from tadas.client import realtime
from tadas.client.client import ApiClient
from tadas.client.realtime import Channel, ChannelRefused, Connect, SocketLike

ORG, USER = uuid4(), uuid4()


def push(seq: int, kind: str = "tasks.task.created") -> str:
    return json.dumps(
        {
            "type": "event",
            "sent_at": None,
            "topic": "entity_changed",
            "payload": {"kind": kind, "target_id": str(uuid4()), "seq": seq, "actor_id": str(USER)},
        }
    )


HELLO = json.dumps(
    {
        "type": "hello",
        "sent_at": None,
        "org_id": str(ORG),
        "user_id": str(USER),
        "seq": 0,
        "ping_interval_seconds": 25,
    }
)


def hello_at(seq: int) -> str:
    return json.dumps({**json.loads(HELLO), "seq": seq})


SUBSCRIBED = json.dumps({"type": "subscribed", "sent_at": None, "topic": "entity_changed"})


def pong(seq: int) -> str:
    return json.dumps({"type": "pong", "sent_at": None, "seq": seq})


class FakeSocket:
    """Frames in order; a `Close` entry ends the session the way the server
    would. Once the frames run out the socket is silent: the first read waits
    (until the channel gives up on it), the next one gets a push."""

    def __init__(self, frames: list[str | Close]) -> None:
        self.frames = list(frames)
        self.silent_reads = 0
        self.sent: list[str] = []

    async def recv(self) -> str | bytes:
        if not self.frames:
            self.silent_reads += 1
            if self.silent_reads == 1:
                await asyncio.sleep(3600)
            self.frames.append(push(1))
        frame = self.frames.pop(0)
        if isinstance(frame, Close):
            raise ConnectionClosedError(frame, None)
        return frame

    async def send(self, message: str) -> None:
        self.sent.append(message)


def transport(
    events: list[dict[str, Any]], ticket_failures: list[Exception | int] | None = None
) -> httpx.MockTransport:
    """`ticket_failures` are consumed one per ticket request before tickets succeed:
    an exception to raise, or a status to answer with."""
    failures = list(ticket_failures or [])

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/realtime/tickets":
            if failures:
                failure = failures.pop(0)
                if isinstance(failure, Exception):
                    raise failure
                return httpx.Response(failure, json={"error": {"code": "down", "message": "x"}})
            return httpx.Response(201, json={"ticket": "tkt_1", "expires_in_seconds": 30})
        if request.url.path == "/v1/events":
            after = int(request.url.params["after_seq"])
            return httpx.Response(200, json=[e for e in events if e["seq"] > after])
        raise AssertionError(request.url)

    return httpx.MockTransport(handle)


def record(seq: int) -> dict[str, Any]:
    return {
        "seq": seq,
        "kind": "tasks.task.updated",
        "target_id": str(uuid4()),
        "produced_at": "2026-09-18T12:00:00Z",
        "actor_id": str(USER),
    }


def client_over(
    events: list[dict[str, Any]], ticket_failures: list[Exception | int] | None = None
) -> ApiClient:
    return ApiClient(
        "http://test",
        app="cli",
        app_version="cli@test",
        token="ses_1",
        transport=transport(events, ticket_failures),
    )


async def collect(channel: Channel, count: int) -> list[int]:
    seqs: list[int] = []
    async for change in channel:
        seqs.append(change.seq)
        if len(seqs) == count:
            break
    return seqs


def connect_to(sockets: list[FakeSocket], urls: list[str]) -> Connect:
    @asynccontextmanager
    async def connect(url: str, headers: dict[str, str]) -> AsyncIterator[SocketLike]:
        urls.append(url)
        assert headers == {"X-App": "cli", "X-App-Version": "cli@test"}
        yield sockets.pop(0)

    return connect


async def test_pushes_arrive_in_order_and_a_gap_is_replayed_from_the_stream() -> None:
    socket = FakeSocket([HELLO, SUBSCRIBED, push(1), push(2), push(2), push(5)])
    urls: list[str] = []
    states: list[str] = []
    channel = Channel(
        client_over([record(3), record(4), record(5)]),
        on_state=states.append,
        connect=connect_to([socket], urls),
    )
    assert await collect(channel, 5) == [1, 2, 3, 4, 5]
    assert channel.cursor == 5
    assert urls == ["ws://test/v1/realtime?ticket=tkt_1"]
    assert json.loads(socket.sent[0]) == {"op": "subscribe", "topic": "entity_changed"}
    assert states == ["connecting", "open"]


async def test_a_pong_past_the_cursor_replays_what_no_frame_announced() -> None:
    # The push for seq 2 was dropped and nothing followed it; the pong says
    # the stream stands at 3, so the client replays after its cursor.
    socket = FakeSocket([HELLO, SUBSCRIBED, push(1), pong(1), pong(3)])
    channel = Channel(client_over([record(2), record(3)]), connect=connect_to([socket], []))
    assert await collect(channel, 3) == [1, 2, 3]
    assert channel.cursor == 3


async def test_a_dropped_socket_reconnects_and_replays_after_the_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(realtime, "BACKOFF_SECONDS", (0.0,))
    first = FakeSocket([HELLO, SUBSCRIBED, push(1), Close(1006, "gone")])
    second = FakeSocket([HELLO, SUBSCRIBED, push(4)])
    urls: list[str] = []
    states: list[str] = []
    channel = Channel(
        client_over([record(1), record(2), record(3)]),
        on_state=states.append,
        connect=connect_to([first, second], urls),
    )
    assert await collect(channel, 4) == [1, 2, 3, 4]
    assert len(urls) == 2
    assert states == ["connecting", "open", "reconnecting", "open"]


async def test_an_api_that_is_down_while_reconnecting_is_waited_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(realtime, "BACKOFF_SECONDS", (0.0,))
    # The API is down when the channel opens: the ticket call fails at the
    # transport, then the API answers 503 while it comes up, then it is back;
    # later the socket drops and the reconnect finds it healthy.
    first = FakeSocket([HELLO, SUBSCRIBED, push(1), Close(1006, "gone")])
    second = FakeSocket([HELLO, SUBSCRIBED, push(2)])
    failures: list[Exception | int] = [httpx.ConnectError("refused"), 503]
    states: list[str] = []
    channel = Channel(
        client_over([record(1)], failures),
        on_state=states.append,
        connect=connect_to([first, second], []),
    )
    assert await collect(channel, 2) == [1, 2]
    assert states == ["connecting", "reconnecting", "open", "reconnecting", "open"]


async def test_a_ticket_refused_with_401_stops_the_channel() -> None:
    channel = Channel(client_over([], [401]), connect=connect_to([], []))
    with pytest.raises(ChannelRefused):
        await collect(channel, 1)
    assert channel.state == "closed"


async def test_what_happened_before_the_first_push_is_replayed_on_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(realtime, "BACKOFF_SECONDS", (0.0,))
    # The stream stands at 4 when the socket opens; nothing arrives before it
    # drops; two events happen meanwhile; the reconnect replays them.
    first = FakeSocket([hello_at(4), SUBSCRIBED, Close(1006, "gone")])
    second = FakeSocket([hello_at(6), SUBSCRIBED, push(7)])
    channel = Channel(
        client_over([record(3), record(5), record(6)]), connect=connect_to([first, second], [])
    )
    assert await collect(channel, 3) == [5, 6, 7]
    assert channel.cursor == 7


async def test_a_refused_ticket_stops_the_channel() -> None:
    socket = FakeSocket([Close(4401, "invalid_credential")])
    channel = Channel(client_over([]), connect=connect_to([socket], []))
    with pytest.raises(ChannelRefused):
        await collect(channel, 1)
    assert channel.state == "closed"


async def test_silence_is_answered_with_a_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(realtime, "MIN_PING_SECONDS", 0.01)
    hello = json.loads(HELLO)
    hello["ping_interval_seconds"] = 0  # clamped to the minimum, which the test shortens
    socket = FakeSocket([json.dumps(hello)])
    channel = Channel(client_over([]), connect=connect_to([socket], []))
    assert await collect(channel, 1) == [1]
    assert socket.sent[1:] == ['{"op": "ping"}']
