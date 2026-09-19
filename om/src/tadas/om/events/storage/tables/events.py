from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import Base, IdentifiableMixin


class Events(IdentifiableMixin, Base):
    __tablename__ = "events"
    # A stream read by seq: org_id leads the one compound index, so it gets no
    # index of its own, and the read by id is served by the primary key.
    __org_id_index__ = False
    __table_args__ = (Index("uq_events_org_id_seq", "org_id", "seq", unique=True),)
    seq: Mapped[int]
    kind: Mapped[str]
    target_id: Mapped[UUID]
    produced_at: Mapped[datetime]
    actor_id: Mapped[UUID]
    request_id: Mapped[UUID]
    app: Mapped[str]
    payload: Mapped[dict[str, Any]]
