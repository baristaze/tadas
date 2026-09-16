from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import (
    Base,
    IdentifiableMixin,
    SoftDeletableMixin,
    TrackableMixin,
)


class Tasks(IdentifiableMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "tasks"
    # A feed: the compound (org_id, id) index sorts by creation time, so
    # org_id gets no single-column index of its own.
    __org_id_index__ = False
    __table_args__ = (Index("ix_tasks_org_id_id", "org_id", "id"),)
    title: Mapped[str]
    notes: Mapped[str]
    status: Mapped[str]
