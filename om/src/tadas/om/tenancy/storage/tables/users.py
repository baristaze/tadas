from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import (
    Base,
    IdentifiableMixin,
    SoftDeletableMixin,
    TrackableMixin,
)


class Users(IdentifiableMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "users"
    # org_id leads the live-identity index, so it gets no index of its own.
    __org_id_index__ = False
    __table_args__ = (
        # One live user per identity in a tenant: the rule add_member reads for,
        # held by the database so two concurrent adds cannot both win.
        Index(
            "uq_users_org_id_identity_id_live",
            "org_id",
            "identity_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_users_identity_id", "identity_id"),
    )
    identity_id: Mapped[UUID]
    email: Mapped[str]
    display_name: Mapped[str]
