from datetime import datetime
from uuid import UUID

from tadas.om.base import Identifiable, Named, SoftDeletable, Trackable
from tadas.om.tenancy.types.role import Role


class ApiKey(Identifiable, Named, Trackable, SoftDeletable):
    """Membership-scoped, expiring, role-capped at its issuer's role. Revoking soft-deletes."""

    user_id: UUID
    key_hash: str
    role: Role
    expires_at: datetime
