"""The durable record of an idempotent request: who sent it, under which
key, what it looked like, and what it produced. Written pending when the
request begins and finished once, then read on every replay."""

from datetime import datetime
from uuid import UUID

from tadas.om.base import Identifiable


class IdempotencyRecord(Identifiable):
    user_id: UUID  # the record is personal to the sender within the tenant
    key: str  # the caller's Idempotency-Key, unique per (tenant, user)
    request_digest: str  # a digest of the request, so a reused key is caught
    status: int | None = None  # the outcome's status; None while the request runs
    body: str | None = None  # the outcome's body; None while the request runs
    created_at: datetime

    @property
    def pending(self) -> bool:
        return self.status is None
