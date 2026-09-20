from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import Base, GlobalIdentifiableMixin, TrackableMixin


class Identities(GlobalIdentifiableMixin, TrackableMixin, Base):
    __tablename__ = "identities"
    __table_args__ = (Index("uq_identities_email", "email", unique=True),)
    email: Mapped[str]
    password_hash: Mapped[str]
    operator_role: Mapped[str | None]
