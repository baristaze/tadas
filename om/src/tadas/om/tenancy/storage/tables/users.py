from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import (
    Base,
    IdentifiableMixin,
    SoftDeletableMixin,
    TrackableMixin,
)


class Users(IdentifiableMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_identity_id", "identity_id"),)
    identity_id: Mapped[UUID]
    email: Mapped[str]
    display_name: Mapped[str]
