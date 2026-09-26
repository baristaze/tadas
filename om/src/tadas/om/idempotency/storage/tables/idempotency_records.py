from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class IdempotencyRecords(IdentifiableMixin, CreatedMixin, Base):
    __tablename__ = "idempotency_records"
    # org_id leads the unique compound index, so it gets no index of its own.
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_idempotency_records_org_id_user_id_key", "org_id", "user_id", "key", unique=True),
        # What the purge reads: the tenant's records by birth.
        Index("ix_idempotency_records_org_id_created_at", "org_id", "created_at"),
        # The pending markers by their attempt. The purge reads a tenant's
        # abandoned attempts through it, and the re-mint's fence, another
        # namespace's statement, reads the one marker its attempt holds; the
        # unique index above cannot serve either, as it leads with the key the
        # caller sent.
        Index(
            "ix_idempotency_records_org_id_attempt_id",
            "org_id",
            "attempt_id",
            postgresql_where=text("status IS NULL"),
        ),
    )
    user_id: Mapped[UUID]
    key: Mapped[str]
    request_digest: Mapped[str]
    target_id: Mapped[UUID]
    attempt_id: Mapped[UUID | None]
    status: Mapped[int | None]
    body: Mapped[str | None]
