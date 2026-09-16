"""Edge idempotency: a creating POST accepts an Idempotency-Key. The outcome
is recorded per tenant and per user under the key, on the same durable
primitive the queue handlers dedupe on, and replayed on a retry. A key seen
with a different request is refused; a key whose first request is still
running is told to wait."""

import hashlib
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, Request, Response
from pydantic import BaseModel

from tadas.infra.observability import OUTCOMES
from tadas.om.exceptions import PlatformException
from tadas.om.idempotency import IdempotencyManagerInterface
from tadas.om.opcontext import OpContext
from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.resolve import container_of
from tadas.services.api.types.common import ErrorBody, ErrorResponse

REPLAYED_HEADER = "Idempotent-Replayed"
JSON = "application/json"


class IdempotencyInProgress(PlatformException):
    """The first request under this key has not finished yet."""

    http_status = 409
    code = "idempotency_in_progress"


def request_digest(method: str, path: str, body: bytes) -> str:
    """What makes two requests the same request: method, path, and body."""
    digest = hashlib.sha256()
    digest.update(f"{method.upper()}\n{path}\n".encode())
    digest.update(body)
    return digest.hexdigest()


class Idempotency:
    """Wraps the one creating call of a route so the outcome cannot escape
    without being recorded: `run` begins the record, calls the handler, and
    finishes the record with whatever the handler produced."""

    def __init__(
        self,
        manager: IdempotencyManagerInterface,
        ctx: OpContext,
        key: str | None,
        digest: str,
    ) -> None:
        self._manager = manager
        self._ctx = ctx
        self._key = key
        self._digest = digest

    async def run(self, status: int, handler: Callable[[], Awaitable[BaseModel]]) -> Response:
        if self._key is None:
            return _json(await handler(), status)
        record = await self._manager.begin(self._ctx, self._key, self._digest)
        if record is not None:
            if record.status is None or record.body is None:
                OUTCOMES.labels(subsystem="idempotency", outcome="in_progress").inc()
                raise IdempotencyInProgress(
                    f"idempotency key {self._key!r} is still being processed"
                )
            OUTCOMES.labels(subsystem="idempotency", outcome="replayed").inc()
            return Response(
                content=record.body,
                status_code=record.status,
                media_type=JSON,
                headers={REPLAYED_HEADER: "true"},
            )
        try:
            view = await handler()
        except PlatformException as error:
            await self._finish(error.http_status, self._error_body(error.code, error.message))
            raise
        except Exception:
            await self._finish(500, self._error_body("internal_error", "internal error"))
            raise
        body = view.model_dump_json()
        await self._finish(status, body)
        OUTCOMES.labels(subsystem="idempotency", outcome="recorded").inc()
        return Response(content=body, status_code=status, media_type=JSON)

    async def _finish(self, status: int, body: str) -> None:
        assert self._key is not None
        await self._manager.finish(self._ctx, self._key, status, body)

    def _error_body(self, code: str, message: str) -> str:
        """The error envelope as the handler would have sent it, so a retry sees
        the same refusal the first attempt saw."""
        error = ErrorBody(code=code, message=message, request_id=self._ctx.request_id)
        return ErrorResponse(error=error).model_dump_json()


def _json(view: BaseModel, status: int) -> Response:
    return Response(content=view.model_dump_json(), status_code=status, media_type=JSON)


async def idempotency(
    request: Request,
    ctx: Ctx,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Idempotency:
    digest = request_digest(request.method, request.url.path, await request.body())
    return Idempotency(container_of(request).managers.idempotency, ctx, idempotency_key, digest)


Idem = Annotated[Idempotency, Depends(idempotency)]
