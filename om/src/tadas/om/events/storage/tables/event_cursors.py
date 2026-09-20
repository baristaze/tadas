from uuid import UUID

from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from tadas.om.storage.tables.base import Base


class EventCursors(Base):
    """One row per tenant: `head` is the last seq the append assigned. The
    append takes `head + 1` under this row's lock inside its own transaction,
    so two appends to one tenant queue here and a rollback returns the number.
    The same row is the tenant's head seq, the number every pong carries."""

    __tablename__ = "event_cursors"
    org_id: Mapped[UUID] = mapped_column(primary_key=True)
    head: Mapped[int] = mapped_column(BigInteger)
