"""The tenancy swimlane: organizations, identities, users, memberships,
and credentials. Owns the identity model and issues tokens; the gateway
only verifies."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.issued import IssuedApiKey, IssuedLogin, IssuedSession
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.user import User

if TYPE_CHECKING:
    # opcontext imports the tenancy entities it carries; this interface only
    # annotates with the context types, so the import stays out of the cycle.
    from datetime import timedelta

    from tadas.om.opcontext import AdminContext, AppContext, CredentialKind, OpContext, Role


class TenancyManagerInterface:
    """Manager of the tenancy swimlane.

    The operations without `ctx` exist before any principal does or act
    across every tenant; each produces a context rather than consuming
    one. They are platform-internal and listed in the exceptions test.
    """

    async def bootstrap(
        self,
        org_name: str,
        slug: str,
        email: str,
        password: str,
        display_name: str,
        *,
        operator: bool = False,
    ) -> Org:
        """Platform-internal: seeds a fresh environment with one org and its owner."""
        ...

    async def login(self, email: str, password: str) -> IssuedLogin:
        """Platform-internal: verifies a sign-in and issues a credential that carries no tenant."""
        ...

    async def exchange_login(self, login_token: str, org_id: UUID) -> IssuedSession:
        """Platform-internal: exchanges a login credential for a tenant-scoped session token."""
        ...

    async def authenticate(
        self,
        credential: str,
        app: AppContext,
        request_id: UUID,
        trace_id: str | None = None,
    ) -> OpContext:
        """Platform-internal: the gateway asks for the principal behind a credential."""
        ...

    async def authenticate_operator(self, credential: str, request_id: UUID) -> AdminContext:
        """Platform-internal: admits a person's own sign-in when the identity is an operator."""
        ...

    async def resume(
        self,
        org_id: UUID,
        credential_kind: CredentialKind,
        credential_id: UUID,
        app: AppContext,
        request_id: UUID,
    ) -> OpContext:
        """Platform-internal: re-checks the credential behind a redeemed socket ticket."""
        ...

    async def service_context(
        self, org_id: UUID, user_id: UUID, app: AppContext, request_id: UUID
    ) -> OpContext:
        """Platform-internal: rebuilds a person's principal under the service role."""
        ...

    async def service_contexts(self, app: AppContext, request_id: UUID) -> list[OpContext]:
        """Platform-internal: one service context per live tenant, for sweeps."""
        ...

    async def get_org(self, ctx: OpContext) -> Org: ...

    async def get_users(self, ctx: OpContext, limit: int) -> list[User]: ...

    async def get_memberships(self, ctx: OpContext, limit: int) -> list[Membership]: ...

    async def get_api_keys(self, ctx: OpContext, limit: int) -> list[ApiKey]: ...

    async def create_api_key(
        self, ctx: OpContext, name: str, role: Role, ttl: timedelta | None = None
    ) -> IssuedApiKey: ...

    async def revoke_api_key(self, ctx: OpContext, api_key_id: UUID) -> ApiKey: ...

    async def get_orgs(self, admin: AdminContext, limit: int) -> list[Org]: ...
