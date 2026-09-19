"""The tenancy swimlane: organizations, identities, users, memberships,
and credentials. Owns the identity model and issues tokens; the gateway
only verifies."""

from abc import ABC, abstractmethod
from datetime import timedelta
from uuid import UUID

from tadas.om.opcontext import AdminContext, AppContext, CredentialKind, OpContext, Role
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.issued import IssuedApiKey, IssuedLogin, IssuedSession, IssuedTicket
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.user import User


class TenancyManagerInterface(ABC):
    """Manager of the tenancy swimlane, on the tenant plane: every operation
    with a context takes `OpContext`. The operator plane is
    `TenancyOperatorManagerInterface`, which takes `AdminContext`.

    The operations without `ctx` exist before any principal does or act
    across every tenant; each produces a context rather than consuming
    one. They are platform-internal and listed in the exceptions test.
    """

    @abstractmethod
    async def bootstrap(
        self,
        org_name: str,
        slug: str,
        email: str,
        password: str,
        display_name: str,
        *,
        operator: bool = False,
        app: AppContext | None = None,
        request_id: UUID | None = None,
    ) -> tuple[OpContext, Org]:
        """Platform-internal: seeds a fresh environment with one org and its owner.

        Produces the owner's context once the identity, org, user, and
        membership exist; the rest of the seeding runs under it. Returns
        that context beside the org.
        """
        ...

    @abstractmethod
    async def add_member(
        self,
        slug: str,
        email: str,
        password: str,
        display_name: str,
        role: Role,
        *,
        app: AppContext | None = None,
        request_id: UUID | None = None,
    ) -> tuple[OpContext, User, bool]:
        """Platform-internal: seeds a person into an existing org, for local and
        test environments; there is no invitation flow yet.

        Produces the context of the org's creator first, and the rest runs
        under it: the identity is created if the email is new (an existing
        identity keeps its password), then the user and the membership, with
        the role capped at the creator's and the write recorded as theirs. A
        person who is already a member is left as is. Returns that context
        beside the user and whether it was created.
        """
        ...

    @abstractmethod
    async def login(self, email: str, password: str) -> IssuedLogin:
        """Platform-internal: verifies a sign-in and issues a credential that carries no tenant."""
        ...

    @abstractmethod
    async def exchange_login(self, login_token: str, org_id: UUID) -> IssuedSession:
        """Platform-internal: exchanges a login credential for a tenant-scoped session token."""
        ...

    @abstractmethod
    async def authenticate(
        self,
        credential: str,
        app: AppContext,
        request_id: UUID,
        trace_id: str | None = None,
    ) -> OpContext:
        """Platform-internal: the gateway asks for the principal behind a credential."""
        ...

    @abstractmethod
    async def authenticate_operator(self, credential: str, request_id: UUID) -> AdminContext:
        """Platform-internal: admits a person's own sign-in when the identity is an operator."""
        ...

    @abstractmethod
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

    @abstractmethod
    async def redeem_ticket(self, ticket: str, app: AppContext, request_id: UUID) -> OpContext:
        """Platform-internal: consumes a socket ticket exactly once and re-checks the
        credential behind it. The gateway holds a ticket, not a principal."""
        ...

    @abstractmethod
    async def service_context(
        self, org_id: UUID, user_id: UUID, app: AppContext, request_id: UUID
    ) -> OpContext:
        """Platform-internal: rebuilds a person's principal under the service role."""
        ...

    @abstractmethod
    async def service_contexts(self, app: AppContext, request_id: UUID) -> list[OpContext]:
        """Platform-internal: one service context per live tenant, for sweeps."""
        ...

    # The principal.

    @abstractmethod
    async def get_org(self, ctx: OpContext) -> Org: ...

    @abstractmethod
    async def get_identity(self, ctx: OpContext) -> Identity:
        """The identity behind the caller's user."""
        ...

    @abstractmethod
    async def update_user(self, ctx: OpContext, user: User) -> User:
        """Copies the display name; email and identity belong to the identity."""
        ...

    @abstractmethod
    async def get_users(self, ctx: OpContext, limit: int) -> list[User]: ...

    @abstractmethod
    async def get_user(self, ctx: OpContext, user_id: UUID) -> User: ...

    # Memberships.

    @abstractmethod
    async def get_memberships(self, ctx: OpContext, limit: int) -> list[Membership]: ...

    @abstractmethod
    async def update_membership_role(self, ctx: OpContext, user_id: UUID, role: Role) -> Membership:
        """Role-capped at the caller's role, for the target's old role and its new one."""
        ...

    @abstractmethod
    async def remove_member(self, ctx: OpContext, user_id: UUID) -> User:
        """Soft-deletes the member's user in this org; their credentials stop resolving."""
        ...

    # Credentials.

    @abstractmethod
    async def get_sessions(self, ctx: OpContext, limit: int) -> list[Session]:
        """The caller's own live sessions in this org."""
        ...

    @abstractmethod
    async def revoke_session(self, ctx: OpContext, session_id: UUID) -> Session: ...

    @abstractmethod
    async def logout(self, ctx: OpContext) -> Session:
        """Revokes the session the caller presented."""
        ...

    @abstractmethod
    async def get_api_keys(self, ctx: OpContext, limit: int) -> list[ApiKey]: ...

    @abstractmethod
    async def create_api_key(
        self,
        ctx: OpContext,
        name: str,
        role: Role,
        ttl: timedelta | None = None,
        api_key_id: UUID | None = None,
    ) -> IssuedApiKey:
        """`api_key_id`, when given, is the id a retried request carries; a key
        that already exists under it raises Conflict, because its secret was
        shown once and cannot be shown again."""
        ...

    @abstractmethod
    async def revoke_api_key(self, ctx: OpContext, api_key_id: UUID) -> ApiKey: ...

    @abstractmethod
    async def purge_deleted(self, ctx: OpContext) -> int:
        """The sweep, for one tenant: hard-deletes removed members (and their
        memberships) and revoked api keys past the retention period; returns how
        many rows went. Erasing a person is this purge; personal data lives in
        named fields (`email`, `display_name`)."""
        ...

    @abstractmethod
    async def issue_ticket(self, ctx: OpContext) -> IssuedTicket:
        """A single-use, short-lived ticket standing for the caller's credential."""
        ...
