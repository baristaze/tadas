from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class SocketTickets(IdentifiableMixin, CreatedMixin, Base):
    __tablename__ = "socket_tickets"
    __table_args__ = (Index("uq_socket_tickets_ticket_hash", "ticket_hash", unique=True),)
    user_id: Mapped[UUID]
    ticket_hash: Mapped[str]
    credential_kind: Mapped[str]
    credential_id: Mapped[UUID]
    expires_at: Mapped[datetime]
    redeemed_at: Mapped[datetime | None]
