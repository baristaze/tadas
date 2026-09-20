"""The two bases every wire type uses, the error envelope, and the list limit."""

from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

LIMIT_DEFAULT = 50
LIMIT_MAX = 200


class View(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    secret_fields: ClassVar[frozenset[str]] = frozenset()
    """The fields that carry a secret in the clear, shown once: the gateway
    stores the idempotent outcome with each of them absent, so a replay answers
    with the row and no secret. Every such field is optional on the wire."""


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(View):
    code: str
    message: str
    request_id: UUID


class ErrorResponse(View):
    error: ErrorBody


def clamp_limit(limit: int) -> int:
    """Lists return a bare list with a server-clamped limit."""
    return max(1, min(limit, LIMIT_MAX))
