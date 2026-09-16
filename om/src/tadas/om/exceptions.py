"""Every exception raised inside the platform is rooted here. The root
carries the status and the stable code a boundary needs to present it."""


class PlatformException(Exception):
    """Root of every exception raised inside the platform."""

    http_status: int = 500
    code: str = "platform_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)

    @property
    def message(self) -> str:
        return str(self.args[0]) if self.args else self.code


class NotFound(PlatformException):
    http_status = 404
    code = "not_found"


class Conflict(PlatformException):
    http_status = 409
    code = "conflict"


class ValidationFailed(PlatformException):
    http_status = 422
    code = "validation_failed"


class NotAuthorized(PlatformException):
    http_status = 403
    code = "not_authorized"


class NotAuthenticated(PlatformException):
    http_status = 401
    code = "not_authenticated"


class StorageException(PlatformException): ...


class TenantMismatch(StorageException, Conflict):
    """A write named a row that belongs to another tenant."""


class CrossRoleStatement(StorageException):
    """A statement touched tables of more than one database role."""

    code = "cross_role_statement"


class TenancyException(PlatformException): ...


class InvalidCredential(TenancyException, NotAuthenticated):
    """The credential is unknown, malformed, or of a kind this route does not accept."""


class CredentialExpired(TenancyException, NotAuthenticated):
    """The credential was valid once and is not any more."""


class NotAnOperator(TenancyException, NotAuthorized):
    """The identity is not on the operator allowlist."""


class WorkException(PlatformException): ...


class DuplicateWorkItem(WorkException, Conflict):
    """Another work item already carries this idempotency key."""


class LeaseLost(WorkException, Conflict):
    """The item is no longer claimed by this worker; another one may hold it."""
