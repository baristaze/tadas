"""Wire types of the event stream: the record a client replays after the
last sequence it saw, and the projection a push carries on the channel."""

from datetime import datetime
from uuid import UUID

from tadas.services.api.types.common import View


class EventView(View):
    """One record of the tenant's append-only stream, paged by `after_seq`."""

    seq: int
    entity: str
    entity_id: UUID
    action: str
    produced_at: datetime


class EntityChangedView(View):
    """What a push says: which record changed, how, and where it sits in the
    stream. `seq` is None for a push whose producer wrote no stream record."""

    entity: str
    entity_id: UUID
    action: str
    seq: int | None
