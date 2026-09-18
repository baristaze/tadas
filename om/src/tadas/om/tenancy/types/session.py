from datetime import datetime
from uuid import UUID

from tadas.om.base import EMPTY_UUID, Identifiable, Trackable
from tadas.om.opcontext import CredentialKind


class Session(Identifiable, Trackable):
    """A login credential (no tenant, stored under the system scope) or a
    tenant-scoped session token. Only the hash of the token is kept."""

    identity_id: UUID
    user_id: UUID = EMPTY_UUID  # EMPTY_UUID while the credential carries no tenant
    token_hash: str
    credential_kind: CredentialKind
    expires_at: datetime
    revoked_at: datetime | None = None
