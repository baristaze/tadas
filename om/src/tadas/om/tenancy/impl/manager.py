import json
import secrets
from datetime import timedelta
from uuid import UUID

from tadas.infra.cache import CacheInterface
from tadas.infra.topics import EntityChangedPayload, Topics, TopicsInterface
from tadas.om.base import EMPTY_UUID, Platform, new_id, utcnow
from tadas.om.events import EventsManagerInterface
from tadas.om.exceptions import (
    Conflict,
    CredentialExpired,
    InvalidCredential,
    NotAnOperator,
    NotAuthorized,
    NotFound,
    ValidationFailed,
)
from tadas.om.opcontext import (
    AdminContext,
    AppContext,
    AppType,
    CredentialKind,
    OpContext,
    Permission,
    Role,
    build_context,
)
from tadas.om.tenancy.manager import TenancyManagerInterface
from tadas.om.tenancy.rules import (
    MAX_API_KEY_TTL,
    PREFIX_FOR_KIND,
    capped_role,
    credential_kind_of,
    hash_password,
    hash_token,
    role_at_most,
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
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.user import User

BOOTSTRAP_APP = AppContext(type=AppType.CLI, version="cli@bootstrap")
"""The app a bootstrap runs as when its caller names none."""

TICKET_KEY = "ticket:"
TICKET_USED_KEY = "ticket-used:"
TICKET_CREDENTIALS = (CredentialKind.SESSION_TOKEN, CredentialKind.API_KEY)
"""The credentials a socket ticket may stand for."""


class TenancyOptions(Platform):
    """Tunables, built once at boot; the manager never reads the environment."""

    login_ttl: timedelta = timedelta(minutes=10)
    session_ttl: timedelta = timedelta(hours=12)
    api_key_ttl: timedelta = MAX_API_KEY_TTL
    ticket_ttl: timedelta = timedelta(seconds=60)
    max_limit: int = 200


def mint_token(kind: CredentialKind) -> str:
    return PREFIX_FOR_KIND[kind] + secrets.token_urlsafe(32)


class TenancyManagerImpl(TenancyManagerInterface):
    def __init__(
        self,
        storage: TenancyStorageInterface,
        events: EventsManagerInterface,
        topics: TopicsInterface,
        cache: CacheInterface,
        options: TenancyOptions,
    ) -> None:
        self._storage = storage
        self._events = events
        self._topics = topics
        self._cache = cache
        self._options = options

    # Operations without a principal.

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
        if await self._storage.read_org_by_slug(slug) is not None:
            raise Conflict(f"org slug {slug!r} is taken")
        now = utcnow()
        identity = await self._storage.read_identity_by_email(email)
        if identity is None:
            identity_id = new_id()
            identity = Identity(
                id=identity_id,
                created_at=now,
                updated_at=now,
                created_by=identity_id,
                email=email,
                password_hash=hash_password(password, secrets.token_bytes(16)),
                is_operator=operator,
            )
            await self._storage.write_identity(identity)
        elif operator and not identity.is_operator:
            identity = identity.model_copy(update={"is_operator": True, "updated_at": now})
            await self._storage.write_identity(identity)
        user_id = new_id()
        org = Org(
            id=new_id(),
            name=org_name,
            created_at=now,
            updated_at=now,
            created_by=user_id,
            slug=slug,
        )
        await self._storage.write_org(org.id, org)
        user = User(
            id=user_id,
            created_at=now,
            updated_at=now,
            created_by=user_id,
            identity_id=identity.id,
            email=email,
            display_name=display_name,
        )
        await self._storage.write_user(org.id, user)
        membership = Membership(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=user_id,
            user_id=user_id,
            role=Role.OWNER,
        )
        await self._storage.write_membership(org.id, membership)
        # The principal now exists; everything after this line runs under it.
        ctx = build_context(
            user=user,
            org=org,
            role=membership.role,
            credential_kind=CredentialKind.INTERNAL,
            app=app or BOOTSTRAP_APP,
            request_id=request_id or new_id(),
            teams=membership.teams,
        )
        return ctx, org

    async def login(self, email: str, password: str) -> IssuedLogin:
        identity = await self._storage.read_identity_by_email(email)
        if identity is None or not verify_password(password, identity.password_hash):
            raise InvalidCredential("email or password is wrong")
        now = utcnow()
        token = mint_token(CredentialKind.LOGIN)
        session = Session(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=identity.id,
            identity_id=identity.id,
            token_hash=hash_token(token),
            credential_kind=CredentialKind.LOGIN,
            expires_at=now + self._options.login_ttl,
        )
        await self._storage.write_session(EMPTY_UUID, session)
        memberships = await self._memberships_of(identity.id)
        return IssuedLogin(token=token, expires_at=session.expires_at, memberships=memberships)

    async def exchange_login(self, login_token: str, org_id: UUID) -> IssuedSession:
        login = await self._live_session(login_token, CredentialKind.LOGIN)
        org, user, membership = await self._principal_in(org_id, login.identity_id)
        now = utcnow()
        token = mint_token(CredentialKind.SESSION_TOKEN)
        session = Session(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=user.id,
            identity_id=login.identity_id,
            user_id=user.id,
            token_hash=hash_token(token),
            credential_kind=CredentialKind.SESSION_TOKEN,
            expires_at=now + self._options.session_ttl,
        )
        await self._storage.write_session(org_id, session)
        return IssuedSession(
            token=token, expires_at=session.expires_at, org=org, user=user, role=membership.role
        )

    async def authenticate(
        self,
        credential: str,
        app: AppContext,
        request_id: UUID,
        trace_id: str | None = None,
    ) -> OpContext:
        kind = credential_kind_of(credential)
        if kind is CredentialKind.SESSION_TOKEN:
            found = await self._storage.read_session_by_token_hash(hash_token(credential))
            if found is None:
                raise InvalidCredential("unknown session token")
            org_id, session = found
            self._check_session(session, CredentialKind.SESSION_TOKEN)
            org, user, membership = await self._principal(org_id, session.user_id)
            return build_context(
                user=user,
                org=org,
                role=membership.role,
                credential_kind=kind,
                app=app,
                request_id=request_id,
                teams=membership.teams,
                trace_id=trace_id,
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
                user=user,
                org=org,
                role=capped_role(api_key.role, membership.role),
                credential_kind=kind,
                app=app,
                request_id=request_id,
                teams=membership.teams,
                trace_id=trace_id,
                credential_id=api_key.id,
            )
        raise InvalidCredential("this route accepts a session token or an api key")

    async def authenticate_operator(self, credential: str, request_id: UUID) -> AdminContext:
        login = await self._live_session(credential, CredentialKind.LOGIN)
        identity = await self._storage.read_identity(login.identity_id)
        if identity is None or not identity.is_operator:
            raise NotAnOperator("this identity is not an operator")
        return AdminContext(
            identity_id=identity.id,
            email=identity.email,
            credential_kind=CredentialKind.LOGIN,
            request_id=request_id,
        )

    async def resume(
        self,
        org_id: UUID,
        credential_kind: CredentialKind,
        credential_id: UUID,
        app: AppContext,
        request_id: UUID,
    ) -> OpContext:
        if credential_kind is CredentialKind.SESSION_TOKEN:
            session = await self._storage.read_session(org_id, credential_id)
            if session is None:
                raise InvalidCredential("the session behind the ticket is gone")
            self._check_session(session, CredentialKind.SESSION_TOKEN)
            org, user, membership = await self._principal(org_id, session.user_id)
            role = membership.role
        elif credential_kind is CredentialKind.API_KEY:
            api_key = await self._storage.read_api_key(org_id, credential_id)
            if api_key is None:
                raise InvalidCredential("the api key behind the ticket is gone")
            self._check_api_key(api_key)
            org, user, membership = await self._principal(org_id, api_key.user_id)
            role = capped_role(api_key.role, membership.role)
        else:
            raise InvalidCredential("a ticket stands for a session token or an api key")
        return build_context(
            user=user,
            org=org,
            role=role,
            credential_kind=CredentialKind.SOCKET_TICKET,
            app=app,
            request_id=request_id,
            teams=membership.teams,
            credential_id=credential_id,
        )

    async def redeem_ticket(self, ticket: str, app: AppContext, request_id: UUID) -> OpContext:
        if credential_kind_of(ticket) is not CredentialKind.SOCKET_TICKET:
            raise InvalidCredential("expected a socket ticket")
        digest = hash_token(ticket)
        # One atomic increment consumes the ticket: only the first redeemer sees 1.
        used, _ = await self._cache.increment(
            EMPTY_UUID, TICKET_USED_KEY + digest, self._options.ticket_ttl
        )
        if used != 1:
            raise InvalidCredential("socket ticket already redeemed")
        raw = await self._cache.get(EMPTY_UUID, TICKET_KEY + digest)
        if raw is None:
            raise InvalidCredential("unknown or expired socket ticket")
        behind = json.loads(raw)
        return await self.resume(
            UUID(behind["org_id"]),
            CredentialKind(behind["credential_kind"]),
            UUID(behind["credential_id"]),
            app,
            request_id,
        )

    async def service_context(
        self, org_id: UUID, user_id: UUID, app: AppContext, request_id: UUID
    ) -> OpContext:
        org, user, membership = await self._principal(org_id, user_id)
        return build_context(
            user=user,
            org=org,
            role=Role.SERVICE,
            credential_kind=CredentialKind.INTERNAL,
            app=app,
            request_id=request_id,
            teams=membership.teams,
        )

    async def service_contexts(self, app: AppContext, request_id: UUID) -> list[OpContext]:
        contexts: list[OpContext] = []
        for org in await self._storage.read_orgs(self._options.max_limit):
            if org.deleted_at is not None:
                continue
            contexts.append(await self.service_context(org.id, org.created_by, app, request_id))
        return contexts

    # The principal.

    async def get_org(self, ctx: OpContext) -> Org:
        ctx.require(Permission.READ)
        org = await self._storage.read_org(ctx.org_id)
        if org is None or org.deleted_at is not None:
            raise NotFound(f"org {ctx.org_id} not found")
        return org

    async def get_identity(self, ctx: OpContext) -> Identity:
        ctx.require(Permission.READ)
        identity = await self._storage.read_identity(ctx.security.user.identity_id)
        if identity is None:
            raise NotFound(f"identity {ctx.security.user.identity_id} not found")
        return identity

    async def update_user(self, ctx: OpContext, user: User) -> User:
        ctx.require(Permission.READ)
        if user.id != ctx.user_id:
            ctx.require(Permission.MANAGE_MEMBERS)
        existing = await self._live_user(ctx, user.id)
        if not user.display_name.strip():
            raise ValidationFailed("display name is required")
        updated = existing.model_copy(
            update={"display_name": user.display_name, "updated_at": utcnow()}
        )
        await self._storage.write_user(ctx.org_id, updated)
        await self._changed(ctx, "user", updated.id, "updated")
        return updated

    async def get_users(self, ctx: OpContext, limit: int) -> list[User]:
        ctx.require(Permission.READ)
        return await self._storage.read_users(ctx.org_id, self._clamp(limit))

    async def get_user(self, ctx: OpContext, user_id: UUID) -> User:
        ctx.require(Permission.READ)
        user = await self._storage.read_user(ctx.org_id, user_id)
        if user is None or user.deleted_at is not None:
            raise NotFound(f"user {user_id} not found")
        return user

    # Memberships.

    async def get_memberships(self, ctx: OpContext, limit: int) -> list[Membership]:
        ctx.require(Permission.READ)
        return await self._storage.read_memberships(ctx.org_id, self._clamp(limit))

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
        updated = membership.model_copy(update={"role": role, "updated_at": utcnow()})
        await self._storage.write_membership(ctx.org_id, updated)
        await self._changed(ctx, "membership", updated.id, "updated")
        return updated

    async def remove_member(self, ctx: OpContext, user_id: UUID) -> User:
        ctx.require(Permission.MANAGE_MEMBERS)
        if user_id == ctx.user_id:
            raise ValidationFailed("a member cannot remove themselves")
        user = await self._live_user(ctx, user_id)
        membership = await self._live_membership(ctx, user_id)
        if not role_at_most(membership.role, ctx.security.role):
            raise NotAuthorized("cannot remove a member above your own role")
        now = utcnow()
        removed = user.model_copy(
            update={"deleted_at": now, "deleted_by": ctx.user_id, "updated_at": now}
        )
        await self._storage.write_user(ctx.org_id, removed)
        await self._storage.write_membership(
            ctx.org_id, membership.model_copy(update={"updated_at": now})
        )
        await self._changed(ctx, "user", removed.id, "deleted")
        return removed

    # Credentials.

    async def get_sessions(self, ctx: OpContext, limit: int) -> list[Session]:
        ctx.require(Permission.READ)
        now = utcnow()
        sessions = await self._storage.read_sessions(ctx.org_id, ctx.user_id, self._clamp(limit))
        return [session for session in sessions if session.expires_at > now]

    async def revoke_session(self, ctx: OpContext, session_id: UUID) -> Session:
        ctx.require(Permission.READ)
        session = await self._storage.read_session(ctx.org_id, session_id)
        if session is None or session.revoked_at is not None:
            raise NotFound(f"session {session_id} not found")
        if session.user_id != ctx.user_id and not ctx.has(Permission.MANAGE_MEMBERS):
            raise NotAuthorized("only the owner of a session or a member manager may revoke it")
        now = utcnow()
        revoked = session.model_copy(update={"revoked_at": now, "updated_at": now})
        await self._storage.write_session(ctx.org_id, revoked)
        return revoked

    async def logout(self, ctx: OpContext) -> Session:
        if ctx.security.credential_kind is not CredentialKind.SESSION_TOKEN:
            raise ValidationFailed("only a session can log out")
        return await self.revoke_session(ctx, ctx.security.credential_id)

    async def get_api_keys(self, ctx: OpContext, limit: int) -> list[ApiKey]:
        ctx.require(Permission.MANAGE_KEYS)
        keys = await self._storage.read_api_keys(ctx.org_id, self._clamp(limit))
        if ctx.has(Permission.MANAGE_MEMBERS):
            return keys
        return [key for key in keys if key.user_id == ctx.user_id]

    async def create_api_key(
        self, ctx: OpContext, name: str, role: Role, ttl: timedelta | None = None
    ) -> IssuedApiKey:
        ctx.require(Permission.MANAGE_KEYS)
        if not role_at_most(role, ctx.security.role):
            raise NotAuthorized(f"cannot issue role {role.value} above {ctx.security.role.value}")
        if ttl is not None and not (timedelta(0) < ttl <= self._options.api_key_ttl):
            raise ValidationFailed(
                f"an api key lives between one second and {self._options.api_key_ttl.days} days"
            )
        now = utcnow()
        key = mint_token(CredentialKind.API_KEY)
        api_key = ApiKey(
            id=new_id(),
            name=name,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            user_id=ctx.user_id,
            key_hash=hash_token(key),
            role=role,
            expires_at=now + (ttl or self._options.api_key_ttl),
        )
        await self._storage.write_api_key(ctx.org_id, api_key)
        await self._changed(ctx, "api_key", api_key.id, "created")
        return IssuedApiKey(key=key, api_key=api_key)

    async def revoke_api_key(self, ctx: OpContext, api_key_id: UUID) -> ApiKey:
        ctx.require(Permission.MANAGE_KEYS)
        api_key = await self._storage.read_api_key(ctx.org_id, api_key_id)
        if api_key is None or api_key.deleted_at is not None:
            raise NotFound(f"api key {api_key_id} not found")
        if api_key.user_id != ctx.user_id and not ctx.has(Permission.MANAGE_MEMBERS):
            raise NotAuthorized("only the owner of a key or a member manager may revoke it")
        now = utcnow()
        revoked = api_key.model_copy(
            update={"deleted_at": now, "deleted_by": ctx.user_id, "updated_at": now}
        )
        await self._storage.write_api_key(ctx.org_id, revoked)
        await self._changed(ctx, "api_key", revoked.id, "deleted")
        return revoked

    async def issue_ticket(self, ctx: OpContext) -> IssuedTicket:
        ctx.require(Permission.READ)
        if ctx.security.credential_kind not in TICKET_CREDENTIALS:
            raise NotAuthorized("a ticket stands for a session token or an api key")
        ticket = mint_token(CredentialKind.SOCKET_TICKET)
        behind = {
            "org_id": str(ctx.org_id),
            "credential_kind": ctx.security.credential_kind.value,
            "credential_id": str(ctx.security.credential_id),
        }
        ttl = self._options.ticket_ttl
        await self._cache.put(
            EMPTY_UUID, TICKET_KEY + hash_token(ticket), json.dumps(behind).encode(), ttl
        )
        return IssuedTicket(ticket=ticket, expires_at=utcnow() + ttl)

    # Operator operations.

    async def get_orgs(self, admin: AdminContext, limit: int) -> list[Org]:
        return await self._storage.read_orgs(self._clamp(limit))

    async def delete_org(self, admin: AdminContext, org_id: UUID) -> Org:
        org = await self._storage.read_org(org_id)
        if org is None or org.deleted_at is not None:
            raise NotFound(f"org {org_id} not found")
        now = utcnow()
        deleted = org.model_copy(
            update={"deleted_at": now, "deleted_by": admin.identity_id, "updated_at": now}
        )
        await self._storage.write_org(org_id, deleted)
        return deleted

    # Helpers.

    def _clamp(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_limit))

    async def _changed(self, ctx: OpContext, entity: str, entity_id: UUID, action: str) -> None:
        """The core row is written; now the stream row, then the push. Every push
        is also a record, so a client that missed the push replays by seq."""
        event = await self._events.record(ctx, entity, entity_id, action, new_id())
        await self._topics.publish(
            Topics.ENTITY_CHANGED,
            EntityChangedPayload(
                idempotency_key=event.idempotency_key,
                produced_at=event.produced_at,
                org_id=ctx.org_id,
                entity=event.entity,
                entity_id=event.entity_id,
                action=event.action,
                seq=event.seq,
            ),
        )

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

    async def _live_session(self, credential: str, kind: CredentialKind) -> Session:
        if credential_kind_of(credential) is not kind:
            raise InvalidCredential(f"expected a {kind.value} credential")
        found = await self._storage.read_session_by_token_hash(hash_token(credential))
        if found is None:
            raise InvalidCredential(f"unknown {kind.value} credential")
        _, session = found
        self._check_session(session, kind)
        return session

    async def _live_user(self, ctx: OpContext, user_id: UUID) -> User:
        """Existence and tenancy, or NotFound."""
        user = await self._storage.read_user(ctx.org_id, user_id)
        if user is None or user.deleted_at is not None:
            raise NotFound(f"user {user_id} not found")
        return user

    async def _live_membership(self, ctx: OpContext, user_id: UUID) -> Membership:
        membership = await self._storage.read_membership_for_user(ctx.org_id, user_id)
        if membership is None:
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
        users = await self._storage.read_users_by_identity(identity_id)
        user_id = next((user.id for user_org, user in users if user_org == org_id), None)
        if user_id is None:
            raise NotAuthorized("this identity is not a member of that org")
        return await self._principal(org_id, user_id)

    async def _memberships_of(self, identity_id: UUID) -> tuple[OrgMembership, ...]:
        found: list[OrgMembership] = []
        for org_id, user in await self._storage.read_users_by_identity(identity_id):
            org = await self._storage.read_org(org_id)
            membership = await self._storage.read_membership_for_user(org_id, user.id)
            if org is None or org.deleted_at is not None or membership is None:
                continue
            found.append(OrgMembership(org=org, user=user, role=membership.role))
        return tuple(found)
