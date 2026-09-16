"""The operator context every operation takes first, and the operator-plane
context that never mixes with it. Roles, permissions, and the table that
maps one to the other live here so that `ctx.require` needs nothing else."""

from enum import Enum
from uuid import UUID

from tadas.om.base import EMPTY_UUID, Platform
from tadas.om.exceptions import NotAuthorized
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.role import (
    ROLE_PERMISSIONS,
    ROLE_RANK,
    CredentialKind,
    Permission,
    Role,
)
from tadas.om.tenancy.types.user import User

__all__ = [
    "ROLE_PERMISSIONS",
    "ROLE_RANK",
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


class AppType(str, Enum):
    PORTAL = "portal"
    ADMIN = "admin"
    CLI = "cli"
    API = "api"
    WORKER = "worker"


class SecurityContext(Platform):
    user: User
    org: Org
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
        return self.security.org.id

    @property
    def user_id(self) -> UUID:
        return self.security.user.id

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
    user: User,
    org: Org,
    role: Role,
    credential_kind: CredentialKind,
    app: AppContext,
    request_id: UUID,
    teams: tuple[UUID, ...] = (),
    trace_id: str | None = None,
    credential_id: UUID = EMPTY_UUID,
) -> OpContext:
    """The one place a tenant context is assembled from its parts."""
    return OpContext(
        security=SecurityContext(
            user=user,
            org=org,
            role=role,
            permissions=ROLE_PERMISSIONS[role],
            teams=teams,
            credential_kind=credential_kind,
            credential_id=credential_id,
        ),
        app=app,
        request_id=request_id,
        trace_id=trace_id,
    )
