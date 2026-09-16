"""The one place botocore's error type is named. Every AWS impl runs its
calls inside `translated()` and catches `ClientError` only through this
module, so a caller only ever sees a platform exception."""

import contextlib
from collections.abc import Iterator

from botocore.exceptions import ClientError

from tadas.infra.exceptions import BackendFailed

__all__ = ["ClientError", "error_code", "translated"]


def error_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", "Unknown"))


@contextlib.contextmanager
def translated(backend: str, operation: str) -> Iterator[None]:
    """Turns any ClientError that escapes the block into BackendFailed. A
    block that maps a code to its own shape (a NotFound) does so inside."""
    try:
        yield
    except ClientError as error:
        raise BackendFailed(backend, operation, error_code(error)) from error
