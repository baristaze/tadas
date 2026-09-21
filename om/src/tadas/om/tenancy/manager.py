"""The tenancy swimlane: organizations, identities, users, memberships,
and credentials. Owns the identity model and issues tokens; the gateway
only verifies."""

from abc import ABC, abstractmethod
from datetime import timedelta
from uuid import UUID

from tadas.om.idempotency.types.attempt import Attempt
from tadas.om.opcontext import (
    CredentialKind,
    IdentityContext,
    OpContext,
    OperatorContext,
    OperatorRole,
    RequestContext,
    Role,
)
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.issued import IssuedApiKey, IssuedLogin, IssuedSession, IssuedTicket
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.page import ApiKeyPage, MembershipPage, OrgMembershipPage, UserPage
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.socket_ticket import SocketPrincipal
from tadas.om.tenancy.types.user import User


class TenancyManagerInterface(ABC):
    """Manager of the tenancy swimlane, on the tenant plane: every operation
    on a principal takes `OpContext`. The operator plane is
    `TenancyOperatorManagerInterface`, which takes `OperatorContext`.

    The transitions come first. Each takes the weakest stage it needs and
    produces a stronger one: `RequestContext` in, `IdentityContext` or
    `OpContext` out; `IdentityContext` in, `OperatorContext` out. They are the
    only constructors of those stages, and the exceptions test names them.
    """

    @abstractmethod
    async def bootstrap(
        self,
        rctx: RequestContext,
        org_name: str,
        slug: str,
        email: str,
        password: str,
        display_name: str,
        *,
        operator_role: OperatorRole | None = None,
    ) -> tuple[OpContext, Org]:
        """Platform-internal: seeds a fresh environment with one org and its owner.

        Produces the owner's context once the identity, org, user, and
        membership exist; the rest of the seeding runs under it. Returns
        that context beside the org. `operator_role` puts the owner's
        identity on the operator allowlist with that role, or widens the
        entry it has; it never narrows one.
        """
        ...

    @abstractmethod
    async def add_member(
        self,
        rctx: RequestContext,
        slug: str,
        email: str,
        password: str,
        display_name: str,
        role: Role,
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
    async def sign_up(
        self,
        rctx: RequestContext,
        email: str,
        password: str,
        display_name: str,
        org_name: str,
        org_slug: str,
    ) -> IssuedLogin:
        """Platform-internal: a person nobody knows yet creates their identity,
        their first org, and the owner membership, in one commit, and is signed
        in. The answer is a sign-in's: the credential that carries no tenant and
        the memberships (the one), so the client goes on through the same
        choice and exchange. An email an identity already holds is Conflict,
        and so is a taken slug; so is a sign-up that raced another for either,
        and nothing lands then. No email is verified, by choice: this is the
        door a deployed environment has, and whether it is open is the
        caller's setting, not this operation's."""
        ...

    @abstractmethod
    async def login(self, rctx: RequestContext, email: str, password: str) -> IssuedLogin:
        """Platform-internal: verifies a sign-in and issues a credential that carries no tenant."""
        ...

    @abstractmethod
    async def authenticate_login(self, rctx: RequestContext, credential: str) -> IdentityContext:
        """Platform-internal: the transition to the identity stage. Verifies the
        person's own sign-in and produces the identity behind it: the login
        credential (`lgn_`), or a live session token (`ses_`), which proves the
        identity of its user as well as the tenant, so a signed-in app lists
        its memberships and switches with the one bearer it holds. A revoked
        or expired session, or one whose user, membership, or org is gone, is
        refused; an api key is refused with InvalidCredential, since it is an
        agent's and not the person's sign-in. Every operation on an identity
        starts here."""
        ...

    @abstractmethod
    async def exchange_login(self, ictx: IdentityContext, org_id: UUID) -> IssuedSession:
        """Platform-internal: exchanges the verified identity for a tenant-scoped
        session token; NotAuthorized when the identity is not a member of
        `org_id`. An identity proven by a session is a switch: that session
        ends in the same write that lands the new one, announced as any
        revocation is, so its socket closes and a tab never holds two live
        sessions. A session another write already ended is refused with
        CredentialExpired and nothing lands."""
        ...

    @abstractmethod
    async def get_identity_memberships(
        self, ictx: IdentityContext, after: UUID | None, limit: int
    ) -> OrgMembershipPage:
        """Platform-internal: no tenant is chosen, so the list is the identity's.
        The places the verified identity holds, each its org, its user, and its
        role, the same choice a sign-in answers with; by user id, a page at a
        time as `get_users` pages. Deleted orgs and ended memberships are not
        listed."""
        ...

    @abstractmethod
    async def authenticate(self, rctx: RequestContext, credential: str) -> OpContext:
        """Platform-internal: the transition to the tenant stage. The gateway asks
        for the principal behind a session token or an api key."""
        ...

    @abstractmethod
    async def admit_operator(self, ictx: IdentityContext) -> OperatorContext:
        """Platform-internal: the transition to the operator stage. Admits the
        verified identity when it is on the operator allowlist, NotAnOperator
        otherwise, with the permissions the entry's role grants. Only the
        login credential admits: the identity stage also accepts a tenant
        session, and a tenant's credential never reaches the operator plane,
        so one is refused with InvalidCredential."""
        ...

    @abstractmethod
    async def resume(
        self,
        rctx: RequestContext,
        org_id: UUID,
        credential_kind: CredentialKind,
        credential_id: UUID,
    ) -> SocketPrincipal:
        """Platform-internal: re-checks the credential behind a redeemed socket
        ticket and yields the socket's context with the credential's expiry,
        the bound on the socket's authority."""
        ...

    @abstractmethod
    async def redeem_ticket(self, rctx: RequestContext, ticket: str) -> SocketPrincipal:
        """Platform-internal: consumes a socket ticket exactly once and re-checks the
        credential behind it. The gateway holds a ticket, not a principal; what
        it gets back is the principal and the instant its authority ends."""
        ...

    @abstractmethod
    async def service_context(self, rctx: RequestContext, org_id: UUID, user_id: UUID) -> OpContext:
        """Platform-internal: the context a claimed work item runs under. Minted
        for the tenant on the service role, with `user_id` kept as the
        attribution: the person authorized the work once, at enqueue, so only
        the org must be live, not their user or membership; a member who has
        left does not stop the work they asked for. A deleted org is refused
        with InvalidCredential."""
        ...

    @abstractmethod
    async def service_contexts(self, rctx: RequestContext) -> list[OpContext]:
        """Platform-internal: one service context per tenant, deleted ones
        included, for sweeps, with one for the system scope (`EMPTY_UUID` as the
        org) first, since login credentials live there and a sweep that never
        visits it lets them pile up. Minted for the tenant, not for a member: it
        carries the tenant, the service role, and the system user (`EMPTY_UUID`)
        as its user id, so a tenant whose members have all left, or that was
        deleted, is still swept; a sweep that skipped a deleted tenant would
        leave its rows and its claimed work forever."""
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
    async def get_users(self, ctx: OpContext, after: UUID | None, limit: int) -> UserPage:
        """The tenant's members, by id, a page at a time: `after` is the id the
        previous page ended on, and `has_more` says another follows."""
        ...

    @abstractmethod
    async def get_user(self, ctx: OpContext, user_id: UUID) -> User: ...

    # Memberships.

    @abstractmethod
    async def get_memberships(
        self, ctx: OpContext, after: UUID | None, limit: int
    ) -> MembershipPage:
        """The tenant's memberships, by user id, a page at a time as `get_users`
        pages: a page ending on the same user id covers the same members, so
        the two lists pair page for page."""
        ...

    @abstractmethod
    async def update_membership_role(self, ctx: OpContext, user_id: UUID, role: Role) -> Membership:
        """Role-capped at the caller's role, for the target's old role and its new one."""
        ...

    @abstractmethod
    async def remove_member(self, ctx: OpContext, user_id: UUID) -> User:
        """Soft-deletes the member's user in this org and ends their membership
        with it; their credentials stop resolving, no list shows them, and no
        role change reaches them."""
        ...

    # Credentials.

    @abstractmethod
    async def get_sessions(self, ctx: OpContext, limit: int) -> list[Session]:
        """The caller's own live sessions in this org, newest first."""
        ...

    @abstractmethod
    async def revoke_session(self, ctx: OpContext, session_id: UUID) -> Session: ...

    @abstractmethod
    async def logout(self, ctx: OpContext) -> Session:
        """Revokes the session the caller presented."""
        ...

    @abstractmethod
    async def get_api_keys(self, ctx: OpContext, after: UUID | None, limit: int) -> ApiKeyPage:
        """The tenant's unrevoked keys for a member manager, the caller's own
        otherwise; newest first, a page at a time, as `get_users` pages."""
        ...

    @abstractmethod
    async def create_api_key(
        self,
        ctx: OpContext,
        name: str,
        role: Role,
        ttl: timedelta | None = None,
        attempt: Attempt | None = None,
    ) -> IssuedApiKey:
        """Role-capped at the caller's role; the service role is refused by name.
        `attempt`, when given, is the attempt a retried request runs under: the
        id it creates on and the token of the idempotency marker holding it. A
        key that already exists under that id is the rerun of a create that
        issues a secret: the secret is re-minted on that row in the same write
        and a fresh `IssuedApiKey` with the same id comes back, since the first
        secret reached no one; the old secret stops authenticating. The re-mint
        lands only while the marker still holds the token, so an attempt that
        lost the marker to a retry cannot invalidate the key that retry already
        returned. Without an attempt the id is fresh and there is no rerun."""
        ...

    @abstractmethod
    async def revoke_api_key(self, ctx: OpContext, api_key_id: UUID) -> ApiKey: ...

    @abstractmethod
    async def purge_deleted(self, ctx: OpContext) -> int:
        """The sweep, for one tenant: hard-deletes removed members (and their
        memberships), revoked or expired api keys, revoked or expired sessions,
        and redeemed or expired socket tickets past the retention period;
        returns how many rows went. Under the system scope it is the expired
        login credentials that go; under a tenant deleted longer ago than the
        retention, every row of the tenant goes and the org row stays as the
        record. Erasing a person is this purge; personal data lives in named
        fields (`email`, `display_name`), which no event about a user carries."""
        ...

    @abstractmethod
    async def tenant_expired(self, ctx: OpContext) -> bool:
        """Platform-internal: True when the tenant's org row is deleted longer ago
        than the retention. Every namespace's sweep asks it before its own
        purge, so one answer decides for the whole system: a tenant past it
        keeps its org row as the record and no row of any other kind."""
        ...

    @abstractmethod
    async def issue_ticket(self, ctx: OpContext) -> IssuedTicket:
        """A single-use, short-lived ticket standing for the caller's credential."""
        ...
