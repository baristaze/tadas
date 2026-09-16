"""One handler translates PlatformException into the error envelope with the
status the exception names; one catch-all turns anything else into a 500
with the same shape. Routers never set error status codes."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from tadas.om.exceptions import PlatformException
from tadas.services.api.gateway.observability import request_id_of
from tadas.services.api.gateway.ratelimit import RateLimited
from tadas.services.api.types.common import ErrorBody, ErrorResponse

log = logging.getLogger(__name__)


def envelope(
    request: Request, status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=request_id_of(request.scope))
    )
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PlatformException)
    async def platform_exception(request: Request, exc: PlatformException) -> JSONResponse:
        headers = None
        if isinstance(exc, RateLimited):
            headers = {"Retry-After": str(max(1, int(exc.retry_after.total_seconds())))}
        return envelope(request, exc.http_status, exc.code, exc.message, headers)

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = "; ".join(
            f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}" for error in exc.errors()
        )
        return envelope(request, 422, "validation_failed", details)

    @app.exception_handler(Exception)
    async def catch_all(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return envelope(request, 500, "internal_error", "internal error")
