"""Edge idempotency: a creating POST accepts an Idempotency-Key. The outcome
is recorded per tenant and per user under the key, on the same durable
primitive the queue handlers dedupe on, and replayed on a retry. Only an
outcome a retry cannot change is recorded: a refusal is replayed, a failure
releases the marker so the retry runs again on the same id. A key seen with
a different request is refused; a key whose first request is still running
is told to wait. The marker names its attempt: an attempt that ran past the
pending lease and lost the marker to a retry is refused when it finishes or
releases, and the refusal is logged and swallowed here, because the retry
owns the marker now and whatever the slow attempt wrote is the row the retry
found."""

import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request, Response
from pydantic import BaseModel

from tadas.infra.observability import OUTCOMES
from tadas.om.base import new_id
from tadas.om.exceptions import IdempotencyAttemptLost, IdempotencyInProgress, PlatformException
from tadas.om.idempotency import IdempotencyManagerInterface
from tadas.om.opcontext import OpContext
from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.resolve import container_of
from tadas.services.api.types.common import ErrorBody, ErrorResponse

log = logging.getLogger(__name__)

REPLAYED_HEADER = "Idempotent-Replayed"
JSON = "application/json"


def request_digest(method: str, path: str, body: bytes) -> str:
    """What makes two requests the same request: method, path, and body."""
    digest = hashlib.sha256()
    digest.update(f"{method.upper()}\n{path}\n".encode())
    digest.update(body)
    return digest.hexdigest()


class Idempotency:
    """Wraps the one creating call of a route so the outcome cannot escape
    without being recorded: `run` begins the record, calls the handler with
    the id the create uses, and finishes the record with whatever the handler
    produced. The id is minted here, before the marker, and travels on it, so
    a retry that takes over an abandoned marker creates on the same id and a
    crash between the create and `finish` cannot end in two rows."""

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
        self.target_id: UUID = new_id()

    async def run(self, status: int, handler: Callable[[UUID], Awaitable[BaseModel]]) -> Response:
        if self._key is None:
            return _json(await handler(self.target_id), status)
        try:
            record = await self._manager.begin(self._ctx, self._key, self._digest, self.target_id)
        except IdempotencyInProgress:
            OUTCOMES.labels(subsystem="idempotency", outcome="in_progress").inc()
            raise
        if record.status is not None and record.body is not None:
            OUTCOMES.labels(subsystem="idempotency", outcome="replayed").inc()
            return Response(
                content=record.body,
                status_code=record.status,
                media_type=JSON,
                headers={REPLAYED_HEADER: "true"},
            )
        attempt_id = record.attempt_id
        try:
            view = await handler(record.target_id)
        except PlatformException as error:
            if error.http_status >= 500:
                await self._release(attempt_id)
            else:
                # A refusal is an outcome a retry cannot change: stored and replayed.
                await self._finish(
                    attempt_id, error.http_status, self._error_body(error.code, error.message)
                )
            raise
        except Exception:
            # A failure is not an outcome: the marker goes, and the retry runs the
            # request again on the same id instead of replaying the failure for good.
            await self._release(attempt_id)
            raise
        body = view.model_dump_json()
        if await self._finish(attempt_id, status, body):
            OUTCOMES.labels(subsystem="idempotency", outcome="recorded").inc()
        return Response(content=body, status_code=status, media_type=JSON)

    async def _finish(self, attempt_id: UUID, status: int, body: str) -> bool:
        assert self._key is not None
        try:
            await self._manager.finish(self._ctx, self._key, attempt_id, status, body)
        except IdempotencyAttemptLost:
            self._lost("finish")
            return False
        return True

    async def _release(self, attempt_id: UUID) -> None:
        assert self._key is not None
        try:
            await self._manager.release(self._ctx, self._key, attempt_id)
        except IdempotencyAttemptLost:
            self._lost("release")
            return
        OUTCOMES.labels(subsystem="idempotency", outcome="released").inc()

    def _lost(self, action: str) -> None:
        """The attempt ran past the pending lease and a retry took the marker
        over; its outcome is the retry's to record, so the refusal ends here."""
        log.warning(
            "idempotency key %r: %s refused, a retry holds the marker now", self._key, action
        )
        OUTCOMES.labels(subsystem="idempotency", outcome="attempt_lost").inc()

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
