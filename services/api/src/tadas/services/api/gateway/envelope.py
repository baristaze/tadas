"""The one error envelope: `{"error": {"code", "message", "request_id"}}`,
rendered from the request id the middleware stamped. The exception handlers
and the middleware's own last resort both produce it from here."""

from uuid import UUID

from fastapi.responses import JSONResponse

from tadas.services.api.types.common import ErrorBody, ErrorResponse

INTERNAL_ERROR = ("internal_error", "internal error")
"""The code and message a client sees for any failure it cannot act on."""


def error_response(
    request_id: UUID,
    status: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, request_id=request_id))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)
