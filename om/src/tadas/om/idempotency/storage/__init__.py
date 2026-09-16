"""Storage of idempotency records. The scope is user-bound within the
tenant: both keys are passed and both are in every WHERE clause."""

from uuid import UUID

from tadas.om.idempotency.types.record import IdempotencyRecord


class IdempotencyStorageInterface:
    async def write_record(self, org_id: UUID, record: IdempotencyRecord) -> None:
        """Raises DuplicateIdempotencyKey when another record carries the same
        (org_id, user_id, key)."""
        ...

    async def read_record(
        self, org_id: UUID, user_id: UUID, key: str
    ) -> IdempotencyRecord | None: ...
