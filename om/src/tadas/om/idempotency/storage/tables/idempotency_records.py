from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class IdempotencyRecords(IdentifiableMixin, CreatedMixin, Base):
    __tablename__ = "idempotency_records"
    # org_id leads the unique compound index, so it gets no index of its own.
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_idempotency_records_org_id_user_id_key", "org_id", "user_id", "key", unique=True),
        # What the re-mint's fence reads: the marker on one target, asked for by
        # another namespace's statement, which the unique index above cannot
        # serve because it leads with the key the caller sent.
        Index("ix_idempotency_records_org_id_target_id", "org_id", "target_id"),
    )
    user_id: Mapped[UUID]
    key: Mapped[str]
    request_digest: Mapped[str]
    target_id: Mapped[UUID]
    attempt_id: Mapped[UUID | None]
    status: Mapped[int | None]
    body: Mapped[str | None]
