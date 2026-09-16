from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class Sessions(IdentifiableMixin, TrackableMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("uq_sessions_token_hash", "token_hash", unique=True),)
    identity_id: Mapped[UUID]
    user_id: Mapped[UUID]
    token_hash: Mapped[str]
    credential_kind: Mapped[str]
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
