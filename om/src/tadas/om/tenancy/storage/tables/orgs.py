from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import (
    Base,
    IdentifiableMixin,
    NamedMixin,
    SoftDeletableMixin,
    TrackableMixin,
)


class Orgs(IdentifiableMixin, NamedMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "orgs"
    # An org's org_id is its own id, which the primary key already serves.
    __org_id_index__ = False
    __table_args__ = (
        # A slug is unique among the living: a deleted org frees it.
        Index("uq_orgs_slug", "slug", unique=True, postgresql_where=text("deleted_at IS NULL")),
    )
    slug: Mapped[str]
