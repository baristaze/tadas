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
        "ping_interval_seconds": 25,
    }
)
SUBSCRIBED = json.dumps({"type": "subscribed", "sent_at": None, "topic": "entity_changed"})


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


def transport(events: list[dict[str, Any]]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/realtime/tickets":
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


def client_over(events: list[dict[str, Any]]) -> ApiClient:
    return ApiClient(
        "http://test", app="cli", app_version="cli@test", token="ses_1", transport=transport(events)
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
