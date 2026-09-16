"""The infra family of platform exceptions. A driver's own error type never
crosses the infra boundary: every impl translates it into one of these."""

from tadas.om.exceptions import PlatformException


class InfraException(PlatformException): ...


class BackendFailed(InfraException):
    """The hosted backend answered with an error the impl cannot map to a
    shape. The message names the backend, the operation, and the backend's
    error code; never a payload or a secret value."""

    code = "backend_failed"

    def __init__(self, backend: str, operation: str, error_code: str) -> None:
        super().__init__(f"{backend} {operation} failed with {error_code}")
