from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class WorkItems(IdentifiableMixin, TrackableMixin, Base):
    __tablename__ = "work_items"
    # org_id leads the sweep's compound index, so it gets no index of its own.
    __org_id_index__ = False
    __table_args__ = (
        # The key collides within its tenant, so the index leads with it. The
        # key alone stays unique beside it while a release that predates the
        # tenant's index may still be serving; the release after drops it.
        Index("uq_work_items_idempotency_key", "idempotency_key", unique=True),
        Index("uq_work_items_org_id_idempotency_key", "org_id", "idempotency_key", unique=True),
        # The purge reads settled items across tenants by their last change.
        Index("ix_work_items_status_updated_at", "status", "updated_at"),
        Index("ix_work_items_lane_status_available_at", "lane", "status", "available_at"),
        Index(
            "ix_work_items_org_id_status_lease_expires_at", "org_id", "status", "lease_expires_at"
        ),
    )
    kind: Mapped[str]
    target_id: Mapped[UUID]
    idempotency_key: Mapped[UUID]
    request_id: Mapped[UUID]
    traceparent: Mapped[str | None]
    payload: Mapped[dict[str, Any]]
    lane: Mapped[str]
    status: Mapped[str]
    available_at: Mapped[datetime]
    claimed_by: Mapped[str | None]
    claim_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None]
    attempts: Mapped[int]
    max_attempts: Mapped[int]
    last_error: Mapped[str | None]
