from sqlalchemy import Index
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
    __table_args__ = (Index("uq_orgs_slug", "slug", unique=True),)
    slug: Mapped[str]
