"""A single-use socket ticket, as a row. It stands for the session or api
key it was minted under; redeeming it is one conditional write on this row,
so a replay is refused by the database, not by a cache."""

from datetime import datetime
from uuid import UUID

from tadas.om.base import Created, Identifiable
from tadas.om.opcontext import CredentialKind


class SocketTicket(Identifiable, Created):
    user_id: UUID
    ticket_hash: str  # only the hash of the ticket is kept
    credential_kind: CredentialKind  # session_token or api_key
    credential_id: UUID
    expires_at: datetime
    redeemed_at: datetime | None = None
