"""Storage of idempotency records. The scope is user-bound within the
tenant: both keys are passed and both are in every WHERE clause."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from tadas.om.idempotency.types.record import IdempotencyRecord


class IdempotencyStorageInterface(ABC):
    @abstractmethod
    async def write_record(self, org_id: UUID, record: IdempotencyRecord) -> None:
        """Raises DuplicateIdempotencyKey when another record carries the same
        (org_id, user_id, key)."""
        ...

    @abstractmethod
    async def read_record(
        self, org_id: UUID, user_id: UUID, key: str
    ) -> IdempotencyRecord | None: ...

    @abstractmethod
    async def release_pending(self, org_id: UUID, user_id: UUID, key: str) -> None:
        """Removes the record under (org_id, user_id, key) while it is still
        pending, so the next attempt begins afresh; a finished record stays."""
        ...

    @abstractmethod
    async def take_over_pending(
        self,
        org_id: UUID,
        user_id: UUID,
        key: str,
        abandoned_before: datetime,
        restarted_at: datetime,
    ) -> IdempotencyRecord | None:
        """Restarts the pending lease of the record under (org_id, user_id, key),
        but only while it is still pending and began before `abandoned_before`:
        one conditional write, so of two retries racing for an abandoned marker
        exactly one takes it over and runs the request again. Returns the record
        as written, or None when nothing matched."""
        ...
