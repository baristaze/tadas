"""The idempotency swimlane: the durable outcome of a request the caller
may retry. The gateway begins a record before it runs a creating request
and finishes it with the outcome; a retry gets the stored record back."""

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
        id the create will use, and returns it: a pending record is the caller's
        to run, with the record's `target_id`, which a take-over keeps from the
        abandoned first attempt; a finished record is replayed. Raises
        IdempotencyInProgress while another attempt holds the marker within its
        lease, and IdempotencyKeyReused when the stored record has another
        digest."""
        ...

    @abstractmethod
    async def finish(self, ctx: OpContext, key: str, status: int, body: str) -> IdempotencyRecord:
        """Records the outcome on the record `begin` wrote; raises NotFound without one."""
        ...
