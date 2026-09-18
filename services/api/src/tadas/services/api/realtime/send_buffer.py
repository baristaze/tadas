"""Per socket: one bounded send buffer and a drainer task that writes it to
the wire. When the buffer is full the oldest frame is dropped and the drop
is logged; the client that notices a gap in the stream replays from storage.
Not to be confused with the transactional outbox of the object model."""

import asyncio
import logging
from collections import deque

from fastapi import WebSocket

from tadas.om.base import utcnow
from tadas.services.api.realtime.envelopes import Envelope

log = logging.getLogger(__name__)


class SendBuffer:
    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._frames: deque[Envelope] = deque()
        self._wakeup = asyncio.Event()
        self.dropped = 0

    def offer(self, envelope: Envelope) -> None:
        frame = envelope.model_copy(update={"sent_at": utcnow()})
        if len(self._frames) >= self._maxsize:
            dropped = self._frames.popleft()
            self.dropped += 1
            log.warning("send buffer full; dropped a %s frame", type(dropped).__name__)
        self._frames.append(frame)
        self._wakeup.set()

    async def drain(self, websocket: WebSocket) -> None:
        while True:
            while self._frames:
                frame = self._frames.popleft()
                await websocket.send_text(frame.model_dump_json())
            self._wakeup.clear()
            await self._wakeup.wait()
