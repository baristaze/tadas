from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import DuplicateIdempotencyKey, IdempotencyKeyReused, NotFound
from tadas.om.idempotency.manager import IdempotencyManagerInterface
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.types.record import IdempotencyRecord
from tadas.om.opcontext import OpContext, Permission


class IdempotencyManagerImpl(IdempotencyManagerInterface):
    def __init__(self, storage: IdempotencyStorageInterface) -> None:
        self._storage = storage

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
