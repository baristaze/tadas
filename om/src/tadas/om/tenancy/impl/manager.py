import asyncio
import secrets
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from tadas.infra.cache import CacheInterface
from tadas.infra.observability import current_traceparent
from tadas.om.base import EMPTY_UUID, Platform, new_id, utcnow
from tadas.om.exceptions import (
    Conflict,
    CredentialExpired,
    InvalidCredential,
    NotAnOperator,
    NotAuthorized,
    NotFound,
    SignInDelayed,
    UniqueKeyTaken,
    ValidationFailed,
)
from tadas.om.idempotency.types.attempt import Attempt
from tadas.om.opcontext import (
    CredentialKind,
    IdentityContext,
    OpContext,
    OperatorContext,
    OperatorRole,
    Permission,
    RequestContext,
    Role,
    build_context,
)
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import OutboxRow, outbox_row, snapshot
from tadas.om.tenancy.impl.creates import (
    MAX_ORGS_PER_IDENTITY,
    add_member_to,
    create_org_with_owner,
    new_identity,
    owner_rows,
    user_snapshot,
    users_of,
)
from tadas.om.tenancy.manager import TenancyManagerInterface
from tadas.om.tenancy.rules import (
    DUMMY_PASSWORD_HASH,
    MAX_API_KEY_TTL,
    PREFIX_FOR_KIND,
    capped_role,
    check_sign_up,
    credential_kind_of,
    hash_password,
    hash_token,
    role_at_most,
    sign_in_delay,
    verify_password,
)
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.issued import (
    IssuedApiKey,
    IssuedLogin,
    IssuedSession,
    IssuedTicket,
    OrgMembership,
)
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.page import ApiKeyPage, MembershipPage, OrgMembershipPage, UserPage
from tadas.om.tenancy.types.role import operator_permissions_of, permissions_of
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.socket_ticket import SocketPrincipal, SocketTicket
from tadas.om.tenancy.types.user import User

TICKET_USED_KEY = "ticket-used:"
"""The cache remembers a redeemed ticket so a replay is refused without a
round trip; the row decides, so a miss (or a cache that is down) costs
one conditional write and nothing else."""
TICKET_CREDENTIALS = (CredentialKind.SESSION_TOKEN, CredentialKind.API_KEY)
"""The credentials a socket ticket may stand for."""
IDENTITY_CREDENTIALS = (CredentialKind.LOGIN, CredentialKind.SESSION_TOKEN)
"""The credentials that prove an identity: the person's own sign-in, and a
session exchanged from it. An api key is an agent's and proves none."""


class TenancyOptions(Platform):
    """Tunables, built once at boot; the manager never reads the environment."""

    login_ttl: timedelta = timedelta(minutes=10)
    session_ttl: timedelta = timedelta(hours=12)
    sign_in_free_failures: int = 3
    """Failed sign-ins in a row an identity may make before the next waits."""
    sign_in_delay_base: timedelta = timedelta(seconds=1)
    sign_in_delay_cap: timedelta = timedelta(minutes=5)
    """The wait starts at the base and doubles with each failure past the
    free ones, up to the cap, whatever address the attempts come from."""
    api_key_ttl: timedelta = MAX_API_KEY_TTL
    ticket_ttl: timedelta = timedelta(seconds=60)
    max_limit: int = 200
    max_orgs_per_identity: int = MAX_ORGS_PER_IDENTITY
    """How many orgs one person may join; the bound on every read of the users
    one identity is. An add past it is refused (`MembershipLimitReached`)."""
    retention: timedelta = timedelta(days=30)
    """Removed members, revoked keys, dead sessions, and spent socket tickets
    are purged this long after they ended."""


def mint_token(kind: CredentialKind) -> str:
    return PREFIX_FOR_KIND[kind] + secrets.token_urlsafe(32)


class TenancyManagerImpl(TenancyManagerInterface):
    def __init__(
        self,
        storage: TenancyStorageInterface,
        relay: OutboxRelayInterface,
        cache: CacheInterface,
        options: TenancyOptions,
    ) -> None:
        self._storage = storage
        self._relay = relay
        self._cache = cache
        self._options = options

    # The transitions: each takes a stage and produces a stronger one.

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
        org, user, membership = await create_org_with_owner(
            self._storage,
            org_id=new_id(),
            org_name=org_name,
            slug=slug,
            email=email,
            password=password,
            display_name=display_name,
            max_orgs=self._options.max_orgs_per_identity,
            operator_role=operator_role,
        )
        # The principal now exists; everything after this line runs under it.
        ctx = build_context(
            rctx,
            user_id=user.id,
            org_id=org.id,
            role=membership.role,
            permissions=permissions_of(membership.role),
            credential_kind=CredentialKind.INTERNAL,
            teams=membership.teams,
        )
        return ctx, org

    async def add_member(
        self,
        rctx: RequestContext,
        slug: str,
        email: str,
        password: str,
        display_name: str,
        role: Role,
    ) -> tuple[OpContext, User, bool]:
        org = await self._storage.read_org_by_slug(slug)
        if org is None or org.deleted_at is not None:
            raise NotFound(f"org {slug!r} not found")
        # The org's creator is the principal; everything after this line runs under it.
        org, creator, membership = await self._principal(org.id, org.created_by)
        ctx = build_context(
            rctx,
            user_id=creator.id,
            org_id=org.id,
            role=membership.role,
            permissions=permissions_of(membership.role),
            credential_kind=CredentialKind.INTERNAL,
            teams=membership.teams,
        )
        ctx.require(Permission.MANAGE_MEMBERS)
        if role is Role.SERVICE:
            raise ValidationFailed("service is not a membership role")
        if not role_at_most(role, ctx.security.role):
            raise NotAuthorized(f"cannot grant role {role.value} above {ctx.security.role.value}")
        user, created = await add_member_to(
            self._storage,
            self._relay,
            org_id=ctx.org_id,
            user_id=new_id(),
            email=email,
            password=password,
            display_name=display_name,
            role=role,
            actor_id=ctx.user_id,
            request=ctx,
            max_orgs=self._options.max_orgs_per_identity,
        )
        return ctx, user, created

    async def sign_up(
        self,
        rctx: RequestContext,
        email: str,
        password: str,
        display_name: str,
        org_name: str,
        org_slug: str,
    ) -> IssuedLogin:
        try:
            check_sign_up(email, password, display_name, org_name, org_slug)
        except ValueError as error:
            raise ValidationFailed(str(error)) from None
        if await self._storage.read_identity_by_email(email) is not None:
            raise Conflict("an account with this email exists; sign in instead")
        if await self._storage.read_org_by_slug(org_slug) is not None:
            raise Conflict(f"org slug {org_slug!r} is taken")
        # scrypt runs off the event loop, as a sign-in's check does.
        password_hash = await asyncio.to_thread(hash_password, password, secrets.token_bytes(16))
        now = utcnow()
        # Always a new identity, never the one an email already names: a
        # sign-up that raced another for the email meets the unique key and
        # lands nothing, instead of adding an org to someone else's identity.
        identity = new_identity(email, password_hash, now)
        org, user, membership = owner_rows(
            new_id(), org_name.strip(), org_slug, identity, display_name.strip(), now
        )
        # One commit: the identity, the org, the owner's user, and the owner's
        # membership. A key taken meanwhile (the email, the slug) is
        # UniqueKeyTaken, a Conflict, and nothing lands.
        await self._storage.create_org_with_owner(org.id, org, user, membership, identity)
        owner = OrgMembership(org=org, user=user, role=membership.role)
        return await self._issue_login(identity, (owner,))

    async def login(self, rctx: RequestContext, email: str, password: str) -> IssuedLogin:
        identity = await self._storage.read_identity_by_email(email)
        now = utcnow()
        # The per-address limit rides the cache and fails open. This one is
        # counted per identity in the tenancy role's own storage, so a guessed
        # identity waits whatever address the guesses come from, and it holds
        # when the cache is down. The wait is checked before the password.
        if identity is not None:
            wait = sign_in_delay(
                identity.failed_sign_ins,
                identity.last_failed_sign_in_at,
                now,
                free=self._options.sign_in_free_failures,
                base=self._options.sign_in_delay_base,
                cap=self._options.sign_in_delay_cap,
            )
            if wait > timedelta(0):
                raise SignInDelayed(wait)
        # The hash is verified on a miss too, against a fixed dummy, so an
        # unknown email costs what a wrong password costs; scrypt runs off the
        # event loop, so a sign-in never stalls every other request.
        stored = DUMMY_PASSWORD_HASH if identity is None else identity.password_hash
        verified = await asyncio.to_thread(verify_password, password, stored)
        if identity is None or not verified:
            if identity is not None:
                await self._storage.record_failed_sign_in(identity.id, now)
            raise InvalidCredential("email or password is wrong")
        if identity.failed_sign_ins:
            await self._storage.clear_failed_sign_ins(identity.id)
        return await self._issue_login(identity, await self._memberships_of(identity.id))

    async def _issue_login(
        self, identity: Identity, memberships: tuple[OrgMembership, ...]
    ) -> IssuedLogin:
        """The credential that carries no tenant, stored under the system scope."""
        now = utcnow()
        token = mint_token(CredentialKind.LOGIN)
        session = Session(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=identity.id,
            updated_by=identity.id,
            identity_id=identity.id,
            token_hash=hash_token(token),
            credential_kind=CredentialKind.LOGIN,
            expires_at=now + self._options.login_ttl,
        )
        await self._storage.write_session(EMPTY_UUID, session)
        return IssuedLogin(token=token, expires_at=session.expires_at, memberships=memberships)

    async def authenticate_login(self, rctx: RequestContext, credential: str) -> IdentityContext:
        kind = credential_kind_of(credential)
        if kind is None or kind not in IDENTITY_CREDENTIALS:
            raise InvalidCredential("expected the sign-in credential or a session token")
        found = await self._storage.read_session_by_token_hash(hash_token(credential))
        if found is None:
            raise InvalidCredential(f"unknown {kind.value} credential")
        org_id, proof = found
        self._check_session(proof, kind)
        if kind is CredentialKind.SESSION_TOKEN:
            # A session proves its user's identity only while it proves the
            # tenant too: the org, the user, and the membership are live.
            await self._principal(org_id, proof.user_id)
        identity = await self._storage.read_identity(proof.identity_id)
        if identity is None:
            raise InvalidCredential("the identity is gone")
        return IdentityContext(
            request_id=rctx.request_id,
            app=rctx.app,
            trace_id=rctx.trace_id,
            caused_by_request_id=rctx.caused_by_request_id,
            identity_id=identity.id,
            email=identity.email,
            credential_kind=kind,
            credential_id=proof.id,
        )

    async def exchange_login(self, ictx: IdentityContext, org_id: UUID) -> IssuedSession:
        org, user, membership = await self._principal_in(org_id, ictx.identity_id)
        now = utcnow()
        token = mint_token(CredentialKind.SESSION_TOKEN)
        session = Session(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=user.id,
            updated_by=user.id,
            identity_id=ictx.identity_id,
            user_id=user.id,
            token_hash=hash_token(token),
            credential_kind=CredentialKind.SESSION_TOKEN,
            expires_at=now + self._options.session_ttl,
        )
        if ictx.credential_kind is CredentialKind.SESSION_TOKEN:
            await self._switch(ictx, org_id, session, now)
        else:
            await self._storage.write_session(org_id, session)
        return IssuedSession(
            token=token, expires_at=session.expires_at, org=org, user=user, role=membership.role
        )

    async def _switch(
        self, ictx: IdentityContext, org_id: UUID, session: Session, now: datetime
    ) -> None:
        """The exchange of a session for another: the one presented ends in the
        write that lands the new one, and its revocation is announced under the
        tenant it belonged to, by its own user, so its socket closes."""
        found = await self._storage.read_session_by_id(ictx.credential_id)
        if found is None:
            raise InvalidCredential("the session behind the switch is gone")
        ended_org_id, presented = found
        self._check_session(presented, CredentialKind.SESSION_TOKEN)
        ended = presented.model_copy(
            update={"revoked_at": now, "updated_at": now, "updated_by": presented.user_id}
        )
        row = OutboxRow(
            id=new_id(),
            created_at=now,
            org_id=ended_org_id,
            kind="tenancy.session.revoked",
            target_id=ended.id,
            payload=snapshot(ended, exclude=frozenset({"token_hash"})),
            actor_id=presented.user_id,
            request_id=ictx.request_id,
            traceparent=current_traceparent(),
            app=ictx.app.type.value,
        )
        try:
            await self._storage.replace_session(org_id, session, ended_org_id, ended, (row,))
        except NotFound:
            raise InvalidCredential("the session behind the switch is gone") from None
        except UniqueKeyTaken:
            raise  # a key of the new session, not the one presented
        except Conflict:
            raise CredentialExpired("session revoked") from None
        await self._relay.relay(ended_org_id, row)

    async def get_identity_memberships(
        self, ictx: IdentityContext, after: UUID | None, limit: int
    ) -> OrgMembershipPage:
        limit = self._clamp(limit)
        rows = await self._storage.read_memberships_by_identity(ictx.identity_id, limit + 1, after)
        return OrgMembershipPage(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    async def authenticate(self, rctx: RequestContext, credential: str) -> OpContext:
        kind = credential_kind_of(credential)
        if kind is CredentialKind.SESSION_TOKEN:
            found = await self._storage.read_session_by_token_hash(hash_token(credential))
            if found is None:
                raise InvalidCredential("unknown session token")
            org_id, session = found
            self._check_session(session, CredentialKind.SESSION_TOKEN)
            org, user, membership = await self._principal(org_id, session.user_id)
            return build_context(
                rctx,
                user_id=user.id,
                org_id=org.id,
                role=membership.role,
                permissions=permissions_of(membership.role),
                credential_kind=kind,
                teams=membership.teams,
                credential_id=session.id,
            )
        if kind is CredentialKind.API_KEY:
            found = await self._storage.read_api_key_by_hash(hash_token(credential))
            if found is None:
                raise InvalidCredential("unknown api key")
            org_id, api_key = found
            self._check_api_key(api_key)
            org, user, membership = await self._principal(org_id, api_key.user_id)
            return build_context(
                rctx,
                user_id=user.id,
                org_id=org.id,
                role=capped_role(api_key.role, membership.role),
                permissions=permissions_of(capped_role(api_key.role, membership.role)),
                credential_kind=kind,
                teams=membership.teams,
                credential_id=api_key.id,
            )
        raise InvalidCredential("this route accepts a session token or an api key")

    async def admit_operator(self, ictx: IdentityContext) -> OperatorContext:
        if ictx.credential_kind is not CredentialKind.LOGIN:
            raise InvalidCredential("the operator plane takes the sign-in credential")
        identity = await self._storage.read_identity(ictx.identity_id)
        if identity is None or identity.operator_role is None:
            raise NotAnOperator("this identity is not an operator")
        return OperatorContext(
            request_id=ictx.request_id,
            app=ictx.app,
            trace_id=ictx.trace_id,
            caused_by_request_id=ictx.caused_by_request_id,
            identity_id=identity.id,
            email=identity.email,
            credential_kind=ictx.credential_kind,
            credential_id=ictx.credential_id,
            permissions=operator_permissions_of(identity.operator_role),
        )

    async def resume(
        self,
        rctx: RequestContext,
        org_id: UUID,
        credential_kind: CredentialKind,
        credential_id: UUID,
    ) -> SocketPrincipal:
        if credential_kind is CredentialKind.SESSION_TOKEN:
            session = await self._storage.read_session(org_id, credential_id)
            if session is None:
                raise InvalidCredential("the session behind the ticket is gone")
            self._check_session(session, CredentialKind.SESSION_TOKEN)
            org, user, membership = await self._principal(org_id, session.user_id)
            role = membership.role
            expires_at = session.expires_at
        elif credential_kind is CredentialKind.API_KEY:
            api_key = await self._storage.read_api_key(org_id, credential_id)
            if api_key is None:
                raise InvalidCredential("the api key behind the ticket is gone")
            self._check_api_key(api_key)
            org, user, membership = await self._principal(org_id, api_key.user_id)
            role = capped_role(api_key.role, membership.role)
            expires_at = api_key.expires_at
        else:
            raise InvalidCredential("a ticket stands for a session token or an api key")
        ctx = build_context(
            rctx,
            user_id=user.id,
            org_id=org.id,
            role=role,
            permissions=permissions_of(role),
            credential_kind=CredentialKind.SOCKET_TICKET,
            teams=membership.teams,
            credential_id=credential_id,
        )
        return SocketPrincipal(ctx=ctx, expires_at=expires_at)

    async def redeem_ticket(self, rctx: RequestContext, ticket: str) -> SocketPrincipal:
        if credential_kind_of(ticket) is not CredentialKind.SOCKET_TICKET:
            raise InvalidCredential("expected a socket ticket")
        digest = hash_token(ticket)
        if await self._cache.get(EMPTY_UUID, TICKET_USED_KEY + digest) is not None:
            raise InvalidCredential("socket ticket already redeemed")
        now = utcnow()
        # One conditional write consumes the ticket: only the first redeemer gets the row.
        consumed = await self._storage.consume_socket_ticket(digest, now)
        if consumed is None:
            raise InvalidCredential("unknown or already redeemed socket ticket")
        org_id, behind = consumed
        await self._cache.put(EMPTY_UUID, TICKET_USED_KEY + digest, b"1", self._options.ticket_ttl)
        if behind.expires_at <= now:
            raise InvalidCredential("socket ticket expired")
        return await self.resume(rctx, org_id, behind.credential_kind, behind.credential_id)

    async def service_context(self, rctx: RequestContext, org_id: UUID, user_id: UUID) -> OpContext:
        # Minted for the tenant on the service role's authority; the person is
        # the attribution, not the authority: they authorized the work once, at
        # enqueue, so neither their user nor their membership is read, and a
        # member who has left does not stop the work they asked for.
        org = await self._storage.read_org(org_id)
        if org is None or org.deleted_at is not None:
            raise InvalidCredential("the org is gone")
        return build_context(
            rctx,
            user_id=user_id,
            org_id=org.id,
            role=Role.SERVICE,
            permissions=permissions_of(Role.SERVICE),
            credential_kind=CredentialKind.INTERNAL,
        )

    async def _every_org(self) -> list[Org]:
        """Every tenant, page by page: a sweep that stopped at the first clamp
        would never reach the tenants behind it."""
        orgs: list[Org] = []
        after_id: UUID | None = None
        while True:
            page = await self._storage.read_orgs(self._options.max_limit, after_id)
            orgs.extend(page)
            if len(page) < self._options.max_limit:
                return orgs
            after_id = page[-1].id

    async def service_contexts(self, rctx: RequestContext) -> list[OpContext]:
        # Minted for the tenant, not for a member: the system user is the actor
        # and no user or membership is read, so it costs one read per page of
        # tenants and a tenant whose members have all left is still swept. So
        # is a deleted tenant: its rows and its claimed work are the sweep's to
        # settle. The system scope comes first: login credentials live under it.
        scopes = [EMPTY_UUID, *(org.id for org in await self._every_org())]
        return [
            build_context(
                rctx,
                user_id=EMPTY_UUID,
                org_id=org_id,
                role=Role.SERVICE,
                permissions=permissions_of(Role.SERVICE),
                credential_kind=CredentialKind.INTERNAL,
            )
            for org_id in scopes
        ]

    # The principal.

    async def get_org(self, ctx: OpContext) -> Org:
        ctx.require(Permission.READ)
        org = await self._storage.read_org(ctx.org_id)
        if org is None or org.deleted_at is not None:
            raise NotFound(f"org {ctx.org_id} not found")
        return org

    async def get_identity(self, ctx: OpContext) -> Identity:
        ctx.require(Permission.READ)
        user = await self._live_user(ctx, ctx.user_id)
        identity = await self._storage.read_identity(user.identity_id)
        if identity is None:
            raise NotFound(f"identity {user.identity_id} not found")
        return identity

    async def update_user(self, ctx: OpContext, user: User) -> User:
        ctx.require(Permission.READ)
        if user.id != ctx.user_id:
            ctx.require(Permission.MANAGE_MEMBERS)
        existing = await self._live_user(ctx, user.id)
        if not user.display_name.strip():
            raise ValidationFailed("display name is required")
        # model_copy does not validate; the copy carries caller input, so it does.
        updated = User.model_validate(
            {
                **existing.model_dump(),
                "display_name": user.display_name,
                "updated_at": utcnow(),
                "updated_by": ctx.user_id,
            }
        )
        await self._write_user(ctx, updated, "updated")
        return updated

    async def get_users(self, ctx: OpContext, after: UUID | None, limit: int) -> UserPage:
        ctx.require(Permission.READ)
        limit = self._clamp(limit)
        rows = await self._storage.read_users(ctx.org_id, after, limit + 1)
        return UserPage(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    async def get_user(self, ctx: OpContext, user_id: UUID) -> User:
        ctx.require(Permission.READ)
        user = await self._storage.read_user(ctx.org_id, user_id)
        if user is None or user.deleted_at is not None:
            raise NotFound(f"user {user_id} not found")
        return user

    # Memberships.

    async def get_memberships(
        self, ctx: OpContext, after: UUID | None, limit: int
    ) -> MembershipPage:
        ctx.require(Permission.READ)
        limit = self._clamp(limit)
        rows = await self._storage.read_memberships(ctx.org_id, limit + 1, after)
        return MembershipPage(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    async def update_membership_role(self, ctx: OpContext, user_id: UUID, role: Role) -> Membership:
        ctx.require(Permission.MANAGE_MEMBERS)
        if role is Role.SERVICE:
            raise ValidationFailed("service is not a membership role")
        if user_id == ctx.user_id:
            raise ValidationFailed("a member cannot change their own role")
        membership = await self._live_membership(ctx, user_id)
        if not role_at_most(membership.role, ctx.security.role):
            raise NotAuthorized("cannot change the role of a member above your own")
        if not role_at_most(role, ctx.security.role):
            raise NotAuthorized(f"cannot grant role {role.value} above {ctx.security.role.value}")
        updated = membership.model_copy(
            update={"role": role, "updated_at": utcnow(), "updated_by": ctx.user_id}
        )
        row = outbox_row(ctx, "tenancy.membership.updated", updated.id, snapshot(updated))
        await self._storage.write_membership(ctx.org_id, updated, (row,))
        await self._relay.relay(ctx.org_id, row)
        return updated

    async def remove_member(self, ctx: OpContext, user_id: UUID) -> User:
        ctx.require(Permission.MANAGE_MEMBERS)
        if user_id == ctx.user_id:
            raise ValidationFailed("a member cannot remove themselves")
        membership = await self._live_membership(ctx, user_id)
        user = await self._live_user(ctx, user_id)
        if not role_at_most(membership.role, ctx.security.role):
            raise NotAuthorized("cannot remove a member above your own role")
        # Their credentials go first, each revoked with its outbox row the way
        # a revocation is, so no key of theirs stays listed. A failure here
        # leaves a member with fewer credentials, which the next remove_member
        # finishes.
        revocations = await self._revoke_credentials_of(ctx, user_id)
        now = utcnow()
        removed = user.model_copy(
            update={
                "deleted_at": now,
                "deleted_by": ctx.user_id,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        # The membership ends with the member: soft-deleted beside the user in
        # one commit, so no read lists it, no role change reaches it during
        # the retention, and no failure leaves a live user without one.
        ended = membership.model_copy(
            update={
                "deleted_at": now,
                "deleted_by": ctx.user_id,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        row = outbox_row(ctx, "tenancy.user.deleted", removed.id, user_snapshot(removed))
        await self._storage.remove_member(ctx.org_id, removed, ended, (row,))
        # The removal is announced first, so a socket of theirs closes because
        # their membership ended, not because a credential was revoked; then
        # each revocation, as the record it is. Every row is durable already:
        # whatever a crash leaves unrelayed, the sweep relays.
        await self._relay.relay(ctx.org_id, row)
        for revocation in revocations:
            await self._relay.relay(ctx.org_id, revocation)
        return removed

    async def _revoke_credentials_of(self, ctx: OpContext, user_id: UUID) -> list[OutboxRow]:
        """Revokes every live session and every unrevoked api key of the user,
        a page at a time until none is left, each landing with its outbox row;
        returns the rows, for the caller to relay in the order it means."""
        rows: list[OutboxRow] = []
        page = self._options.max_limit
        while sessions := await self._storage.read_sessions(ctx.org_id, user_id, utcnow(), page):
            now = utcnow()
            for session in sessions:
                revoked = session.model_copy(
                    update={"revoked_at": now, "updated_at": now, "updated_by": ctx.user_id}
                )
                row = self._session_row(ctx, revoked, "revoked")
                await self._storage.write_session(ctx.org_id, revoked, (row,))
                rows.append(row)
        while keys := await self._storage.read_api_keys(ctx.org_id, None, page, user_id):
            now = utcnow()
            for api_key in keys:
                revoked_key = api_key.model_copy(
                    update={
                        "deleted_at": now,
                        "deleted_by": ctx.user_id,
                        "updated_at": now,
                        "updated_by": ctx.user_id,
                    }
                )
                row = outbox_row(
                    ctx, "tenancy.api_key.deleted", revoked_key.id, self._key_snapshot(revoked_key)
                )
                await self._storage.write_api_key(ctx.org_id, revoked_key, (row,))
                rows.append(row)
        return rows

    # Credentials.

    async def get_sessions(self, ctx: OpContext, limit: int) -> list[Session]:
        ctx.require(Permission.READ)
        # Live at the storage: a page of dead sessions cannot hide a live one.
        return await self._storage.read_sessions(
            ctx.org_id, ctx.user_id, utcnow(), self._clamp(limit)
        )

    async def revoke_session(self, ctx: OpContext, session_id: UUID) -> Session:
        ctx.require(Permission.READ)
        session = await self._storage.read_session(ctx.org_id, session_id)
        if session is None or session.revoked_at is not None:
            raise NotFound(f"session {session_id} not found")
        if session.user_id != ctx.user_id and not ctx.has(Permission.MANAGE_MEMBERS):
            raise NotAuthorized("only the owner of a session or a member manager may revoke it")
        now = utcnow()
        revoked = session.model_copy(
            update={"revoked_at": now, "updated_at": now, "updated_by": ctx.user_id}
        )
        # Announced like any change: the socket this session opened, in
        # whichever process holds it, closes on the row the relay publishes.
        await self._write_session(ctx, revoked, "revoked")
        return revoked

    async def logout(self, ctx: OpContext) -> Session:
        if ctx.security.credential_kind is not CredentialKind.SESSION_TOKEN:
            raise ValidationFailed("only a session can log out")
        return await self.revoke_session(ctx, ctx.security.credential_id)

    async def get_api_keys(self, ctx: OpContext, after: UUID | None, limit: int) -> ApiKeyPage:
        ctx.require(Permission.MANAGE_KEYS)
        # A member manager sees the tenant's keys; anyone else their own, filtered
        # at the storage so a page of other people's keys cannot hide theirs.
        own_only = None if ctx.has(Permission.MANAGE_MEMBERS) else ctx.user_id
        limit = self._clamp(limit)
        # One row past the page, kept out of it: `has_more` is then a fact
        # about the rows, so no key is left unreachable behind a fixed limit.
        rows = await self._storage.read_api_keys(ctx.org_id, after, limit + 1, own_only)
        return ApiKeyPage(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    async def create_api_key(
        self,
        ctx: OpContext,
        name: str,
        role: Role,
        ttl: timedelta | None = None,
        attempt: Attempt | None = None,
    ) -> IssuedApiKey:
        ctx.require(Permission.MANAGE_KEYS)
        # A key never mints its successor. Revoking a leaked key has to end the
        # access it gave; a key that can issue another one outlives its own
        # revocation, and nothing ties the successor back to it. `logout`
        # gates on the credential kind for the same reason.
        if ctx.security.credential_kind is CredentialKind.API_KEY:
            raise NotAuthorized("an api key cannot create another; sign in to create one")
        if role is Role.SERVICE:
            raise ValidationFailed("service is not an api key role")
        if not role_at_most(role, ctx.security.role):
            raise NotAuthorized(f"cannot issue role {role.value} above {ctx.security.role.value}")
        if ttl is not None and not (timedelta(0) < ttl <= self._options.api_key_ttl):
            raise ValidationFailed(
                f"an api key lives between one second and {self._options.api_key_ttl.days} days"
            )
        now = utcnow()
        key = mint_token(CredentialKind.API_KEY)
        api_key = ApiKey(
            id=attempt.target_id if attempt else new_id(),
            name=name,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            user_id=ctx.user_id,
            key_hash=hash_token(key),
            role=role,
            expires_at=now + (ttl or self._options.api_key_ttl),
        )
        # A create that issues a secret: the row as stored is not enough on a
        # rerun, because the secret is a digest there and was shown to no one
        # (the marker stored no outcome). The one storage method inserts the
        # key, or re-mints the secret on the row the id already names, and the
        # re-mint lands only while the marker still holds this attempt.
        row = outbox_row(ctx, "tenancy.api_key.created", api_key.id, self._key_snapshot(api_key))
        stored, created = await self._storage.issue_api_key(
            ctx.org_id, api_key, (row,), attempt.attempt_id if attempt else None
        )
        if created:
            await self._relay.relay(ctx.org_id, row)
        return IssuedApiKey(key=key, api_key=stored)

    async def revoke_api_key(self, ctx: OpContext, api_key_id: UUID) -> ApiKey:
        ctx.require(Permission.MANAGE_KEYS)
        api_key = await self._storage.read_api_key(ctx.org_id, api_key_id)
        if api_key is None or api_key.deleted_at is not None:
            raise NotFound(f"api key {api_key_id} not found")
        if api_key.user_id != ctx.user_id and not ctx.has(Permission.MANAGE_MEMBERS):
            raise NotAuthorized("only the owner of a key or a member manager may revoke it")
        now = utcnow()
        revoked = api_key.model_copy(
            update={
                "deleted_at": now,
                "deleted_by": ctx.user_id,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        await self._write_api_key(ctx, revoked, "deleted")
        return revoked

    async def purge_deleted(self, ctx: OpContext) -> int:
        ctx.require(Permission.MANAGE_MEMBERS)
        if await self.tenant_expired(ctx):
            # The tenant itself is past the retention: every row of it goes.
            return await self._storage.purge_tenant(ctx.org_id)
        return await self._storage.purge_deleted(ctx.org_id, utcnow() - self._options.retention)

    async def tenant_expired(self, ctx: OpContext) -> bool:
        ctx.require(Permission.READ)
        org = await self._storage.read_org(ctx.org_id)
        before = utcnow() - self._options.retention
        return org is not None and org.deleted_at is not None and org.deleted_at < before

    async def issue_ticket(self, ctx: OpContext) -> IssuedTicket:
        ctx.require(Permission.READ)
        if ctx.security.credential_kind not in TICKET_CREDENTIALS:
            raise NotAuthorized("a ticket stands for a session token or an api key")
        ticket = mint_token(CredentialKind.SOCKET_TICKET)
        now = utcnow()
        behind = SocketTicket(
            id=new_id(),
            created_at=now,
            user_id=ctx.user_id,
            ticket_hash=hash_token(ticket),
            credential_kind=ctx.security.credential_kind,
            credential_id=ctx.security.credential_id,
            expires_at=now + self._options.ticket_ttl,
        )
        await self._storage.write_socket_ticket(ctx.org_id, behind)
        return IssuedTicket(ticket=ticket, expires_at=behind.expires_at)

    # Helpers.

    def _clamp(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_limit))

    # The core row and its outbox row land in one storage call; the relay then
    # appends the event and pushes at once, and the sweep catches what a crash
    # left behind.

    async def _write_user(self, ctx: OpContext, user: User, action: str) -> None:
        row = outbox_row(ctx, f"tenancy.user.{action}", user.id, user_snapshot(user))
        await self._storage.write_user(ctx.org_id, user, (row,))
        await self._relay.relay(ctx.org_id, row)

    @staticmethod
    def _session_row(ctx: OpContext, session: Session, action: str) -> OutboxRow:
        # The snapshot never carries the hash; the event is a record, not a credential.
        return outbox_row(
            ctx,
            f"tenancy.session.{action}",
            session.id,
            snapshot(session, exclude=frozenset({"token_hash"})),
        )

    async def _write_session(self, ctx: OpContext, session: Session, action: str) -> None:
        row = self._session_row(ctx, session, action)
        await self._storage.write_session(ctx.org_id, session, (row,))
        await self._relay.relay(ctx.org_id, row)

    @staticmethod
    def _key_snapshot(api_key: ApiKey) -> Mapping[str, Any]:
        # The snapshot never carries the hash; the event is a record, not a credential.
        return snapshot(api_key, exclude=frozenset({"key_hash"}))

    async def _write_api_key(self, ctx: OpContext, api_key: ApiKey, action: str) -> None:
        row = outbox_row(ctx, f"tenancy.api_key.{action}", api_key.id, self._key_snapshot(api_key))
        await self._storage.write_api_key(ctx.org_id, api_key, (row,))
        await self._relay.relay(ctx.org_id, row)

    @staticmethod
    def _check_session(session: Session, kind: CredentialKind) -> None:
        if session.credential_kind is not kind:
            raise InvalidCredential("credential kind does not match its prefix")
        if session.revoked_at is not None:
            raise CredentialExpired("session revoked")
        if session.expires_at <= utcnow():
            raise CredentialExpired("session expired")

    @staticmethod
    def _check_api_key(api_key: ApiKey) -> None:
        if api_key.deleted_at is not None:
            raise CredentialExpired("api key revoked")
        if api_key.expires_at <= utcnow():
            raise CredentialExpired("api key expired")

    async def _live_user(self, ctx: OpContext, user_id: UUID) -> User:
        """Existence and tenancy, or NotFound."""
        user = await self._storage.read_user(ctx.org_id, user_id)
        if user is None or user.deleted_at is not None:
            raise NotFound(f"user {user_id} not found")
        return user

    async def _live_membership(self, ctx: OpContext, user_id: UUID) -> Membership:
        """The membership of a live user, or NotFound: a removed member has no
        membership to read or change, whatever the row says."""
        await self._live_user(ctx, user_id)
        membership = await self._storage.read_membership_for_user(ctx.org_id, user_id)
        if membership is None or membership.deleted_at is not None:
            raise NotFound(f"membership of user {user_id} not found")
        return membership

    async def _principal(self, org_id: UUID, user_id: UUID) -> tuple[Org, User, Membership]:
        org = await self._storage.read_org(org_id)
        if org is None or org.deleted_at is not None:
            raise InvalidCredential("the org is gone")
        user = await self._storage.read_user(org_id, user_id)
        if user is None or user.deleted_at is not None:
            raise InvalidCredential("the user is gone")
        membership = await self._storage.read_membership_for_user(org_id, user_id)
        if membership is None:
            raise InvalidCredential("the membership is gone")
        return org, user, membership

    async def _principal_in(self, org_id: UUID, identity_id: UUID) -> tuple[Org, User, Membership]:
        """The principal a verified identity is in `org_id`, or NotAuthorized: the
        sign-in is good, the tenant is not theirs, so a client keeps its login
        and picks another tenant. A gone org, user, or membership is refused the
        same way; InvalidCredential is for a credential that fails, and a login
        that names a tenant it cannot enter has not failed."""
        users = await users_of(self._storage, identity_id, self._options.max_orgs_per_identity)
        user = next((user for user_org, user in users if user_org == org_id), None)
        if user is None:
            raise NotAuthorized("this identity is not a member of that org")
        org = await self._storage.read_org(org_id)
        if org is None or org.deleted_at is not None:
            raise NotAuthorized("that org is gone")
        membership = await self._storage.read_membership_for_user(org_id, user.id)
        if membership is None:
            raise NotAuthorized("this identity is no longer a member of that org")
        return org, user, membership

    async def _memberships_of(self, identity_id: UUID) -> tuple[OrgMembership, ...]:
        found: list[OrgMembership] = []
        most = self._options.max_orgs_per_identity
        for org_id, user in await users_of(self._storage, identity_id, most):
            org = await self._storage.read_org(org_id)
            membership = await self._storage.read_membership_for_user(org_id, user.id)
            if org is None or org.deleted_at is not None or membership is None:
                continue
            found.append(OrgMembership(org=org, user=user, role=membership.role))
        return tuple(found)
