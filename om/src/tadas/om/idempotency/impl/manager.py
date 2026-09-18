from datetime import timedelta

from tadas.om.base import Platform, new_id, utcnow
from tadas.om.exceptions import DuplicateIdempotencyKey, IdempotencyKeyReused, NotFound
from tadas.om.idempotency.manager import IdempotencyManagerInterface
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.types.record import IdempotencyRecord
from tadas.om.opcontext import OpContext, Permission


class IdempotencyOptions(Platform):
    pending_ttl: timedelta = timedelta(minutes=2)
    """A pending record older than this was abandoned by a crash between the
    marker and its outcome; the next retry takes it over and runs the request
    again, so the marker never suppresses work for good."""


class IdempotencyManagerImpl(IdempotencyManagerInterface):
    def __init__(self, storage: IdempotencyStorageInterface, options: IdempotencyOptions) -> None:
        self._storage = storage
        self._options = options

    async def begin(
        self, ctx: OpContext, key: str, request_digest: str
    ) -> IdempotencyRecord | None:
        ctx.require(Permission.WRITE)
        pending = IdempotencyRecord(
            id=new_id(),
            user_id=ctx.user_id,
            key=key,
            request_digest=request_digest,
            created_at=utcnow(),
        )
        try:
            # The unique index is the dedupe: the first writer wins, every other
            # writer reads what it wrote.
            await self._storage.write_record(ctx.org_id, pending)
        except DuplicateIdempotencyKey:
            stored = await self._storage.read_record(ctx.org_id, ctx.user_id, key)
            if stored is None:
                raise
            if stored.request_digest != request_digest:
                raise IdempotencyKeyReused(
                    f"idempotency key {key!r} was used for a different request"
                ) from None
            if stored.pending and stored.created_at < utcnow() - self._options.pending_ttl:
                # Abandoned: the marker was written and its effect never landed.
                await self._storage.write_record(
                    ctx.org_id, stored.model_copy(update={"created_at": utcnow()})
                )
                return None
            return stored
        return None

    async def finish(self, ctx: OpContext, key: str, status: int, body: str) -> IdempotencyRecord:
        ctx.require(Permission.WRITE)
        stored = await self._storage.read_record(ctx.org_id, ctx.user_id, key)
        if stored is None:
            raise NotFound(f"idempotency key {key!r} was never begun")
        finished = stored.model_copy(update={"status": status, "body": body})
        await self._storage.write_record(ctx.org_id, finished)
        return finished
