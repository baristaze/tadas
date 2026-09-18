"""Wire types of the event stream: the record a client replays after the
last sequence it saw, and the projection a push carries on the channel."""

from datetime import datetime
from uuid import UUID

from tadas.services.api.types.common import View


class EventView(View):
    """One record of the tenant's append-only stream, paged by `after_seq`.
    `kind` is "<namespace>.<entity>.<action>", or an audit kind; the payload
    stays inside, an event is a record and not a second read path."""

    seq: int
    kind: str
    target_id: UUID
    produced_at: datetime


class EntityChangedView(View):
    """What a push says: which record changed, how, and where it sits in the
    stream. Every push has a record, so `seq` is always present."""

    kind: str
    target_id: UUID
    seq: int
