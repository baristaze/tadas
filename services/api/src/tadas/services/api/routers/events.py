"""The event stream: a client that reconnects, or sees a gap on the channel,
asks for everything after the last sequence number it saw."""

from typing import Annotated

from fastapi import APIRouter, Query

from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.resolve import EventsService
from tadas.services.api.types.common import LIMIT_DEFAULT
from tadas.services.api.types.events import EventView

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventView])
async def list_events(
    ctx: Ctx,
    events: EventsService,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: int = LIMIT_DEFAULT,
) -> list[EventView]:
    return await events.get_events(ctx, after_seq, limit)
