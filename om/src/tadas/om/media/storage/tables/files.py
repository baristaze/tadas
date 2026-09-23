from uuid import UUID

from sqlalchemy import BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column

from tadas.om.storage.tables.base import (
    Base,
    IdentifiableMixin,
    NamedMixin,
    SoftDeletableMixin,
    TrackableMixin,
)


class Files(IdentifiableMixin, NamedMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "files"
    # A subject's files by id, the sweep's two reads, and the usage sum; each
    # read leads with org_id, so org_id gets no index of its own.
    __org_id_index__ = False
    __table_args__ = (
        Index("ix_files_org_id_purpose_subject_id_id", "org_id", "purpose", "subject_id", "id"),
        Index("ix_files_org_id_deleted_at", "org_id", "deleted_at"),
        Index("ix_files_org_id_status_created_at", "org_id", "status", "created_at"),
    )
    key: Mapped[str]
    extension: Mapped[str]
    content_type: Mapped[str]
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    purpose: Mapped[str]
    subject_id: Mapped[UUID | None]
    status: Mapped[str]
