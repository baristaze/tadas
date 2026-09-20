"""The idempotency swimlane: the durable outcome of a request the caller
may retry. The gateway begins a record before it runs a creating request
and finishes it with the outcome; a retry gets the stored record back. The
record names the attempt that holds it, and finish and release are that
attempt's alone: an attempt that ran past the pending lease and lost the
marker to a retry is refused, like a worker whose lease has passed."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.idempotency.types.record import IdempotencyRecord
from tadas.om.opcontext import OpContext


class IdempotencyManagerInterface(ABC):
    @abstractmethod
    async def begin(
        self, ctx: OpContext, key: str, request_digest: str, target_id: UUID
    ) -> IdempotencyRecord:
        """Writes a pending record for (tenant, user, key) carrying `target_id`, the
        id the create will use, and a freshly minted `attempt_id`, and returns it:
        a pending record is the caller's to run, with the record's `target_id`,
        which a take-over keeps from the abandoned first attempt, and the
        record's `attempt_id`, which a take-over replaces; a finished record is
        replayed. Raises IdempotencyInProgress while another attempt holds the
        marker within its lease, and IdempotencyKeyReused when the stored record
        has another digest."""
        ...

    @abstractmethod
    async def finish(
        self, ctx: OpContext, key: str, attempt_id: UUID, status: int, body: str
    ) -> IdempotencyRecord:
        """Records the outcome on the record `begin` wrote, in one write conditional
        on `attempt_id` still holding it. Only an outcome a retry cannot change
        belongs here: a refusal, never a failure. Raises NotFound without a record
        under the key, and IdempotencyAttemptLost (a Conflict) when the record is
        finished already or a retry took it over: the caller's work, if it
        landed, is the row the retry found, and the retry's outcome is the one
        replayed."""
        ...

    @abstractmethod
    async def purge(self, ctx: OpContext) -> int:
        """The sweep, for one tenant: deletes finished records past the retention
        and pending ones past ten times the pending lease, a marker no retry
        came back for; returns how many. A key purged is a key free again."""
        ...

    @abstractmethod
    async def release(self, ctx: OpContext, key: str, attempt_id: UUID) -> None:
        """Drops the pending record `begin` wrote, because the attempt failed in a
        way a retry may change; the next attempt begins afresh on the same key.
        One write conditional on `attempt_id` still holding the record; raises
        IdempotencyAttemptLost when it does not, so an attempt that lost the
        marker cannot release what a retry now holds."""
        ...
