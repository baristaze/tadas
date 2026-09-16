from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped, mapped_column

from tadas.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class Memberships(IdentifiableMixin, TrackableMixin, Base):
    __tablename__ = "memberships"
    # org_id leads the unique compound index, so it gets no index of its own.
    org_id: Mapped[UUID] = mapped_column(sort_order=-999)
    __table_args__ = (Index("uq_memberships_org_id_user_id", "org_id", "user_id", unique=True),)
    user_id: Mapped[UUID]
    role: Mapped[str]
    teams: Mapped[list[str]]
