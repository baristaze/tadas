from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import (
    Base,
    IdentifiableMixin,
    NamedMixin,
    SoftDeletableMixin,
    TrackableMixin,
)


class ApiKeys(IdentifiableMixin, NamedMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("uq_api_keys_key_hash", "key_hash", unique=True),)
    user_id: Mapped[UUID]
    key_hash: Mapped[str]
    role: Mapped[str]
    expires_at: Mapped[datetime]
