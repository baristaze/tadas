from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class BillingDeliveries(IdentifiableMixin, CreatedMixin, Base):
    __tablename__ = "billing_deliveries"
    # The purge reads a tenant's marks by age, so org_id leads that index and
    # gets none of its own.
    __org_id_index__ = False
    __table_args__ = (Index("ix_billing_deliveries_org_id_created_at", "org_id", "created_at"),)
    event_id: Mapped[str]
    event_type: Mapped[str]
