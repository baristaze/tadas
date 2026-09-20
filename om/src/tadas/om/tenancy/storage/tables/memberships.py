from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import (
    Base,
    IdentifiableMixin,
    SoftDeletableMixin,
    TrackableMixin,
)


class Memberships(IdentifiableMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "memberships"
    # org_id leads the sweep's index, so it gets no single-column one.
    __org_id_index__ = False
    __table_args__ = (
        # One live membership per user in a tenant: an ended one frees the key.
        Index(
            "uq_memberships_org_id_user_id",
            "org_id",
            "user_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # The sweep's index, as on users: the unique one is among the living,
        # and the purge reads exactly the rows it leaves out.
        Index("ix_memberships_org_id_deleted_at", "org_id", "deleted_at"),
    )
    user_id: Mapped[UUID]
    role: Mapped[str]
    teams: Mapped[list[str]]
