"""Storage of idempotency records. The scope is user-bound within the
tenant: both keys are passed and both are in every WHERE clause. The writes
that move a pending record (take over, re-arm, finish, release) are
conditional in the statement itself and report what they matched: a
take-over, a re-arm, and a finish return the record as written or None, a
release returns whether the attempt went. Nothing here raises for a refused
attempt; the manager names it."""

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
    async def finish_pending(
        self, org_id: UUID, user_id: UUID, key: str, attempt_id: UUID, status: int, body: str
    ) -> IdempotencyRecord | None:
        """One conditional statement: stores the outcome on the record under
        (org_id, user_id, key) only while it is still pending and held by
        `attempt_id`. Returns the record as written, or None when nothing
        matched: no such record, already finished, or held by another attempt."""
        ...

    @abstractmethod
    async def release_pending(
        self, org_id: UUID, user_id: UUID, key: str, attempt_id: UUID
    ) -> bool:
        """One conditional statement: clears the attempt of the record under
        (org_id, user_id, key) only while it is still pending and held by
        `attempt_id`. The record stays, with its digest and its target id and no
        attempt, so the next retry re-arms it and reruns on the same id. Returns
        whether the attempt went; a finished record is untouched, and so is one
        another attempt holds."""
        ...

    @abstractmethod
    async def purge_records(
        self, org_id: UUID, finished_before: datetime, pending_before: datetime
    ) -> int:
        """For the sweep, per tenant: deletes finished and released records that
        began before `finished_before` (past the retention, a retry begins
        afresh) and held pending ones that began before `pending_before` (a
        marker no retry ever came back for); returns how many. The one hard
        delete of the namespace."""
        ...

    @abstractmethod
    async def take_over_pending(
        self,
        org_id: UUID,
        user_id: UUID,
        key: str,
        abandoned_before: datetime,
        restarted_at: datetime,
        attempt_id: UUID,
    ) -> IdempotencyRecord | None:
        """Restarts the pending lease of the record under (org_id, user_id, key)
        and stamps `attempt_id` as its holder, but only while it is still pending,
        held by an attempt, and began before `abandoned_before`: one conditional
        write, so of two retries racing for an abandoned marker exactly one takes
        it over and runs the request again, and the attempt that lost it can no
        longer finish or release it. Returns the record as written, or None when
        nothing matched; a released marker is re-armed, never taken over."""
        ...

    @abstractmethod
    async def rearm_released(
        self, org_id: UUID, user_id: UUID, key: str, restarted_at: datetime, attempt_id: UUID
    ) -> IdempotencyRecord | None:
        """Stamps `attempt_id` on the record under (org_id, user_id, key) and
        restarts its pending lease, but only while it has no attempt and no
        outcome, a marker a failure released: one conditional write, so of two
        retries racing for a released marker exactly one re-arms it and reruns
        the request on the marker's target id, and the other finds it held.
        Returns the record as written, or None when nothing matched."""
        ...
