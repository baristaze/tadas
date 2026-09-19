"""The durable record of an idempotent request: who sent it, under which
key, what it looked like, and what it produced. Written pending when the
request begins and finished once, then read on every replay."""

from uuid import UUID

from tadas.om.base import Created, Identifiable


class IdempotencyRecord(Identifiable, Created):
    user_id: UUID  # the record is personal to the sender within the tenant
    key: str  # the caller's Idempotency-Key, unique per (tenant, user)
    request_digest: str  # a digest of the request, so a reused key is caught
    target_id: UUID  # the id the create uses, minted before the marker; a take-over keeps it
    status: int | None = None  # the outcome's status; None while the request runs
    body: str | None = None  # the outcome's body; None while the request runs

    @property
    def pending(self) -> bool:
        return self.status is None
