"""The operation context every operation takes first, and the operator
context that never mixes with it. Roles, permissions, credential kinds, and
app types are declared here, so this module imports nothing above `base.py`
and the tenancy namespace reads them rather than the other way round."""

from enum import Enum
from uuid import UUID

from tadas.om.base import EMPTY_UUID, Platform
from tadas.om.exceptions import NotAuthorized

__all__ = [
    "AdminContext",
    "AppContext",
    "AppType",
    "CredentialKind",
    "OpContext",
    "Permission",
    "Role",
    "SecurityContext",
    "build_context",
]


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    SERVICE = "service"  # a worker acting on a person's earlier request


class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_KEYS = "manage_keys"


class CredentialKind(str, Enum):
    API_KEY = "api_key"
    SESSION_TOKEN = "session_token"
    LOGIN = "login"
    SOCKET_TICKET = "socket_ticket"
    INTERNAL = "internal"


class AppType(str, Enum):
    PORTAL = "portal"
    ADMIN = "admin"
    CLI = "cli"
    API = "api"
    WORKER = "worker"


class SecurityContext(Platform):
    """Ids and facts, never entities: a manager that needs the user or the org
    loads it, so a role change is seen on the next request."""

    user_id: UUID
    org_id: UUID
    role: Role
    permissions: tuple[Permission, ...]
    teams: tuple[UUID, ...] = ()
    credential_kind: CredentialKind
    credential_id: UUID = EMPTY_UUID  # the session or key; EMPTY_UUID for internal contexts


class AppContext(Platform):
    type: AppType
    version: str  # e.g. "portal@0.1.0"


class OpContext(Platform):
    security: SecurityContext
    app: AppContext
    request_id: UUID
    trace_id: str | None = None

    @property
    def org_id(self) -> UUID:
        return self.security.org_id

    @property
    def user_id(self) -> UUID:
        return self.security.user_id

    def has(self, permission: Permission) -> bool:
        return permission in self.security.permissions

    def require(self, permission: Permission) -> None:
        if not self.has(permission):
            raise NotAuthorized(f"{self.security.role.value} lacks {permission.value}")

    def in_team(self, team_id: UUID) -> bool:
        return team_id in self.security.teams


class AdminContext(Platform):
    """The operator plane. No org_id, on purpose."""

    identity_id: UUID
    email: str
    credential_kind: CredentialKind
    request_id: UUID


def build_context(
    *,
    user_id: UUID,
    org_id: UUID,
    role: Role,
    permissions: tuple[Permission, ...],
    credential_kind: CredentialKind,
    app: AppContext,
    request_id: UUID,
    teams: tuple[UUID, ...] = (),
    trace_id: str | None = None,
    credential_id: UUID = EMPTY_UUID,
) -> OpContext:
    """The one place a tenant context is assembled from its parts. The
    permissions come from the tenancy namespace's role table, which is a
    pure rule this module does not import."""
    return OpContext(
        security=SecurityContext(
            user_id=user_id,
            org_id=org_id,
            role=role,
            permissions=permissions,
            teams=teams,
            credential_kind=credential_kind,
            credential_id=credential_id,
        ),
        app=app,
        request_id=request_id,
        trace_id=trace_id,
    )
