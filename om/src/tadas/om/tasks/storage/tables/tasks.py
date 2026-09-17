from uuid import UUID

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
    # Two lists per org: the open one in manual order, the done one newest
    # first. Each has its compound index, so org_id gets none of its own.
    __org_id_index__ = False
    __table_args__ = (
        Index("ix_tasks_org_id_status_position", "org_id", "status", "position"),
        Index("ix_tasks_org_id_status_updated_at_id", "org_id", "status", "updated_at", "id"),
    )
    title: Mapped[str]
    notes: Mapped[str]
    status: Mapped[str]
    assignee_id: Mapped[UUID | None]
    position: Mapped[float]
