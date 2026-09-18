from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class OutboxRows(IdentifiableMixin, CreatedMixin, Base):
    __tablename__ = "outbox_rows"
    # The sweep reads pending rows across tenants, oldest first, and purges
    # done ones by time; both walk (done_at, id), so org_id keeps its own index.
    __table_args__ = (Index("ix_outbox_rows_done_at_id", "done_at", "id"),)
    kind: Mapped[str]
    target_id: Mapped[UUID]
    payload: Mapped[dict[str, Any]]
    actor_id: Mapped[UUID]
    request_id: Mapped[UUID]
    app: Mapped[str]
    done_at: Mapped[datetime | None]
