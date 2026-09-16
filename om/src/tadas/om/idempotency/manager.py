"""The idempotency swimlane: the durable outcome of a request the caller
may retry. The gateway begins a record before it runs a creating request
and finishes it with the outcome; a retry gets the stored record back."""

from tadas.om.idempotency.types.record import IdempotencyRecord
from tadas.om.opcontext import OpContext


class IdempotencyManagerInterface:
    async def begin(
        self, ctx: OpContext, key: str, request_digest: str
    ) -> IdempotencyRecord | None:
        """Writes a pending record for (tenant, user, key) and returns None when the
        request is new. Returns the stored record on a replay, pending or finished.
        Raises IdempotencyKeyReused when the stored record has another digest."""
        ...

    async def finish(self, ctx: OpContext, key: str, status: int, body: str) -> IdempotencyRecord:
        """Records the outcome on the record `begin` wrote; raises NotFound without one."""
        ...
