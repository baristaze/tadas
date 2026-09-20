"""Per socket, the send buffer is bounded: a full one drops its oldest frame,
logs the drop, and counts it, and the drainer writes what is left, in order."""

import asyncio
import json
import logging
from typing import cast

import pytest
from fastapi import WebSocket

from tadas.services.api.realtime.envelopes import PongEnvelope
from tadas.services.api.realtime.send_buffer import SendBuffer

LOGGER = "tadas.services.api.realtime.send_buffer"


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.written = asyncio.Event()

    async def send_text(self, data: str) -> None:
        self.sent.append(data)
        self.written.set()


async def drained(buffer: SendBuffer, count: int) -> list[int]:
    """Runs the drainer until `count` frames are on the wire; the seqs, in order."""
    socket = FakeSocket()
    drainer = asyncio.create_task(buffer.drain(cast(WebSocket, socket)))
    try:
        while len(socket.sent) < count:
            socket.written.clear()
            await asyncio.wait_for(socket.written.wait(), timeout=1)
    finally:
        drainer.cancel()
    return [json.loads(frame)["seq"] for frame in socket.sent]


async def test_a_full_buffer_drops_the_oldest_frame_logs_and_counts_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    buffer = SendBuffer(maxsize=2)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for seq in (1, 2, 3):
            buffer.offer(PongEnvelope(seq=seq))

    assert buffer.dropped == 1
    assert [record.getMessage() for record in caplog.records] == [
        "send buffer full; dropped a PongEnvelope frame"
    ]
    assert await drained(buffer, 2) == [2, 3]


async def test_a_buffer_with_room_drops_nothing(caplog: pytest.LogCaptureFixture) -> None:
    buffer = SendBuffer(maxsize=3)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for seq in (1, 2, 3):
            buffer.offer(PongEnvelope(seq=seq))

    assert buffer.dropped == 0
    assert caplog.records == []
    assert await drained(buffer, 3) == [1, 2, 3]
