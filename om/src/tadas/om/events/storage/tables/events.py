from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import Base, IdentifiableMixin


class Events(IdentifiableMixin, Base):
    __tablename__ = "events"
    # A feed and a stream: org_id leads both compound indexes, so it gets no
    # index of its own.
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_events_org_id_seq", "org_id", "seq", unique=True),
        Index("ix_events_org_id_id", "org_id", "id"),
    )
    seq: Mapped[int]
    entity: Mapped[str]
    entity_id: Mapped[UUID]
    action: Mapped[str]
    produced_at: Mapped[datetime]
    idempotency_key: Mapped[UUID]
    actor_id: Mapped[UUID]
