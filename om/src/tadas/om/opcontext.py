"""The context an operation takes first, in two orthogonal ideas.

Stages are concrete frozen types, one per amount of evidence a request has
gathered: `RequestContext` (a request exists), `IdentityContext` (a person
is verified), `OpContext` (a membership is established), `AdminContext`
(an operator is admitted). A subclass is a refinement, so every stage is
accepted where a weaker one is asked for. Each stage is produced by exactly
one transition on the tenancy manager and nowhere else; a function that
takes a stage relies on its invariant instead of re-checking it.

Scopes are structural views (`Protocol`) over what a stage carries:
`RequestScope`, `TenantScope`, `ActorScope`, `CredentialScope`, and the one
named composition, `ProvenanceScope`. A function that reads only a few
fields declares the scope it reads, and its callers keep passing the stage
they hold.

Roles, permissions, credential kinds, and app types are declared here, so
this module imports nothing above `base.py` and the tenancy namespace reads
them rather than the other way round."""

from enum import Enum
from typing import Protocol
from uuid import UUID

from tadas.om.base import EMPTY_UUID, Platform
from tadas.om.exceptions import NotAuthorized

__all__ = [
    "ActorScope",
    "AdminContext",
    "AppContext",
    "AppType",
    "CredentialKind",
    "CredentialScope",
    "IdentityContext",
    "OpContext",
    "Permission",
    "ProvenanceScope",
    "RequestContext",
    "RequestScope",
    "Role",
    "SecurityContext",
    "TenantScope",
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


# Stages: refinement by evidence.


class RequestContext(Platform):
    """The weakest stage: a request exists, nobody is known yet. Minted once
    at the edge (the gateway, the worker loop, an ops command)."""

    request_id: UUID
    app: AppContext
    trace_id: str | None = None


class IdentityContext(RequestContext):
    """A person is verified by their own sign-in. No tenant chosen, on purpose:
    the credential behind it carries none."""

    identity_id: UUID
    email: str
    credential_kind: CredentialKind
    credential_id: UUID


class OpContext(RequestContext):
    """A membership is established: the person is a user of one tenant with a
    role. What a tenant operation knows about the person is the user inside
    the tenant, not the identity across tenants, so this is not an
    `IdentityContext`."""

    security: SecurityContext

    @property
    def org_id(self) -> UUID:
        return self.security.org_id

    @property
    def user_id(self) -> UUID:
        return self.security.user_id

    @property
    def credential_kind(self) -> CredentialKind:
        return self.security.credential_kind

    @property
    def credential_id(self) -> UUID:
        return self.security.credential_id

    def has(self, permission: Permission) -> bool:
        return permission in self.security.permissions

    def require(self, permission: Permission) -> None:
        if not self.has(permission):
            raise NotAuthorized(f"{self.security.role.value} lacks {permission.value}")

    def in_team(self, team_id: UUID) -> bool:
        return team_id in self.security.teams


class AdminContext(IdentityContext):
    """The operator plane: an identity on the operator allowlist. No org_id,
    on purpose. No field of its own: the type is the evidence, and only the
    tenancy manager's `admit_operator` constructs it."""


# Scopes: composable capability views. Every member is a read-only property,
# so a frozen field and a property both satisfy it.


class RequestScope(Protocol):
    @property
    def request_id(self) -> UUID: ...

    @property
    def app(self) -> AppContext: ...


class TenantScope(Protocol):
    @property
    def org_id(self) -> UUID: ...


class ActorScope(TenantScope, Protocol):
    """There is no actor without a tenant."""

    @property
    def user_id(self) -> UUID: ...


class CredentialScope(Protocol):
    @property
    def credential_kind(self) -> CredentialKind: ...

    @property
    def credential_id(self) -> UUID: ...


class ProvenanceScope(ActorScope, RequestScope, Protocol):
    """Who, under which request, from which app: the provenance a write
    records. A named composition because provenance is a domain concept."""


def build_context(
    rctx: RequestContext,
    *,
    user_id: UUID,
    org_id: UUID,
    role: Role,
    permissions: tuple[Permission, ...],
    credential_kind: CredentialKind,
    teams: tuple[UUID, ...] = (),
    credential_id: UUID = EMPTY_UUID,
) -> OpContext:
    """The one place a tenant context is assembled from its parts: the request
    stage it refines and the security facts. The permissions come from the
    tenancy namespace's role table, which is a pure rule this module does not
    import."""
    return OpContext(
        request_id=rctx.request_id,
        app=rctx.app,
        trace_id=rctx.trace_id,
        security=SecurityContext(
            user_id=user_id,
            org_id=org_id,
            role=role,
            permissions=permissions,
            teams=teams,
            credential_kind=credential_kind,
            credential_id=credential_id,
        ),
    )
