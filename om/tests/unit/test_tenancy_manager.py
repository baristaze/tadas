import asyncio
import secrets
import threading
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.factories import make_user
from contracts.outbox_storage import claim_all

from tadas.infra.cache import CacheInterface, CacheScope
from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.topics import EntityChangedPayload, TopicPayload, Topics
from tadas.om.base import EMPTY_UUID, new_id, utcnow
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.exceptions import (
    Conflict,
    CredentialExpired,
    InvalidCredential,
    MembershipLimitReached,
    NotAnOperator,
    NotAuthorized,
    NotFound,
    UniqueKeyTaken,
    ValidationFailed,
)
from tadas.om.idempotency.storage.impl.memory import IdempotencyStorageMemoryImpl
from tadas.om.idempotency.types.attempt import Attempt, lease_bound
from tadas.om.idempotency.types.record import IdempotencyRecord
from tadas.om.opcontext import (
    AppContext,
    AppType,
    CredentialKind,
    OpContext,
    OperatorRole,
    Permission,
    RequestContext,
    Role,
)
from tadas.om.outbox.impl.relay import OutboxRelayImpl
from tadas.om.outbox.relay import OutboxRelayInterface
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.tasks.storage.impl.memory import TasksStorageMemoryImpl
from tadas.om.tenancy.impl.manager import TenancyManagerImpl, TenancyOptions
from tadas.om.tenancy.impl.operator import TenancyOperatorManagerImpl, TenancyOperatorOptions
from tadas.om.tenancy.rules import DUMMY_PASSWORD_HASH, hash_password, hash_token, verify_password
from tadas.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.socket_ticket import SocketPrincipal
from tadas.om.tenancy.types.user import PERSONAL_FIELDS, User

APP = AppContext(type=AppType.PORTAL, version="portal@test")


def request(app: AppContext = APP) -> RequestContext:
    """The request stage a test mints at its edge, one per call."""
    return RequestContext(request_id=new_id(), app=app)


class DownCache(CacheInterface):
    """A backend that cannot be reached: every read is a miss, every write is lost."""

    async def get(self, org_id: UUID, key: str) -> bytes | None:
        return None

    async def put(self, org_id: UUID, key: str, value: bytes, ttl: timedelta) -> None:
        return None

    async def invalidate(self, org_id: UUID, key: str) -> None:
        return None

    async def increment(self, org_id: UUID, key: str, ttl: timedelta) -> tuple[int, timedelta]:
        return 0, ttl

    def describe(self) -> str:
        return "cache=down"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.fixture
def infra(tmp_path: Path) -> InfraLocalImpl:
    return InfraLocalImpl(tmp_path)


@pytest.fixture
def outbox() -> OutboxStorageMemoryImpl:
    return OutboxStorageMemoryImpl()


@pytest.fixture
def markers() -> IdempotencyStorageMemoryImpl:
    return IdempotencyStorageMemoryImpl()


@pytest.fixture
def storage(
    outbox: OutboxStorageMemoryImpl, markers: IdempotencyStorageMemoryImpl
) -> TenancyStorageMemoryImpl:
    return TenancyStorageMemoryImpl(outbox, markers)


async def begin_attempt(
    markers: IdempotencyStorageMemoryImpl, ctx: OpContext, key: str, target_id: UUID
) -> Attempt:
    """What the gateway does before a creating request: a pending marker on the
    id the create uses, under a token of its own, and the attempt that carries
    both down to the write."""
    attempt_id = new_id()
    await markers.write_record(
        ctx.org_id,
        IdempotencyRecord(
            id=new_id(),
            created_at=utcnow(),
            user_id=ctx.user_id,
            key=key,
            request_digest="digest",
            target_id=target_id,
            attempt_id=attempt_id,
        ),
    )
    return Attempt(target_id=target_id, attempt_id=attempt_id)


def make_manager(
    storage: TenancyStorageMemoryImpl,
    infra: InfraLocalImpl,
    options: TenancyOptions | None = None,
    cache: CacheInterface | None = None,
    outbox: OutboxStorageMemoryImpl | None = None,
) -> TenancyManagerImpl:
    # A relay over its own outbox is enough where the sweep never runs; the
    # fixture below shares the one the storage lands rows in.
    relay = OutboxRelayImpl(
        outbox or OutboxStorageMemoryImpl(), EventStorageMemoryImpl(), infra.get_topics()
    )
    return TenancyManagerImpl(
        storage,
        relay,
        cache or infra.get_cache(CacheScope.REALTIME_TICKET),
        options or TenancyOptions(),
    )


@pytest.fixture
def manager(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> TenancyManagerImpl:
    return make_manager(storage, infra, outbox=outbox)


@pytest.fixture
def operator(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> TenancyOperatorManagerImpl:
    events = EventStorageMemoryImpl()
    relay = OutboxRelayImpl(outbox, events, infra.get_topics())
    return TenancyOperatorManagerImpl(
        storage, TasksStorageMemoryImpl(outbox), events, relay, TenancyOperatorOptions()
    )


async def sign_in(manager: TenancyManagerImpl, email: str, org_id: UUID) -> OpContext:
    login = await manager.login(request(), email, "pw-1234")
    issued = await manager.exchange_login(
        await manager.authenticate_login(request(), login.token), org_id
    )
    return await manager.authenticate(request(), issued.token)


async def add_member(
    storage: TenancyStorageMemoryImpl, org_id: UUID, email: str, role: Role
) -> User:
    """Seeds a second member straight into storage; there is no invitation flow yet."""
    now = utcnow()
    identity_id, user_id = new_id(), new_id()
    await storage.write_identity(
        Identity(
            id=identity_id,
            created_at=now,
            updated_at=now,
            created_by=identity_id,
            updated_by=identity_id,
            email=email,
            password_hash=hash_password("pw-1234", secrets.token_bytes(16)),
        )
    )
    user = User(
        id=user_id,
        created_at=now,
        updated_at=now,
        created_by=user_id,
        updated_by=user_id,
        identity_id=identity_id,
        email=email,
        display_name=email.split("@")[0].title(),
    )
    await storage.write_user(org_id, user)
    await storage.write_membership(
        org_id,
        Membership(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=user_id,
            updated_by=user_id,
            user_id=user_id,
            role=role,
        ),
    )
    return user


async def test_bootstrap_produces_the_owners_context(manager: TenancyManagerImpl) -> None:
    seed = request(AppContext(type=AppType.CLI, version="cli@test"))
    ctx, org = await manager.bootstrap(seed, "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    assert ctx.org_id == org.id
    assert ctx.security.role is Role.OWNER
    assert ctx.security.credential_kind is CredentialKind.INTERNAL
    # The owner's context refines the request stage the seeding minted.
    assert ctx.app.type is AppType.CLI and ctx.request_id == seed.request_id
    assert (await manager.get_org(ctx)) == org
    assert [u.id for u in (await manager.get_users(ctx, None, limit=10)).items] == [ctx.user_id]
    issued = await manager.create_api_key(ctx, "seed", Role.MEMBER)
    assert issued.api_key.created_by == ctx.user_id


async def test_bootstrap_login_exchange_authenticate(manager: TenancyManagerImpl) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    assert [m.org.id for m in login.memberships] == [org.id]
    assert login.memberships[0].role is Role.OWNER

    issued = await manager.exchange_login(
        await manager.authenticate_login(request(), login.token), org.id
    )
    ctx = await manager.authenticate(request(), issued.token)
    assert ctx.org_id == org.id
    assert ctx.user_id == issued.user.id
    assert ctx.security.role is Role.OWNER
    assert ctx.security.credential_kind is CredentialKind.SESSION_TOKEN
    assert ctx.has(Permission.MANAGE_MEMBERS)
    assert (await manager.get_org(ctx)) == org
    assert [u.id for u in (await manager.get_users(ctx, None, limit=10)).items] == [issued.user.id]


async def test_bootstrap_refuses_a_taken_slug(manager: TenancyManagerImpl) -> None:
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    with pytest.raises(Conflict):
        await manager.bootstrap(request(), "Acme 2", "acme", "bob@example.test", "pw-1234", "Bob")


async def test_a_deleted_org_frees_its_slug(
    manager: TenancyManagerImpl, operator: TenancyOperatorManagerImpl
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    await manager.bootstrap(
        request(),
        "Ops",
        "ops",
        "root@example.test",
        "pw-1234",
        "Root",
        operator_role=OperatorRole.WRITE,
    )
    admin = await manager.admit_operator(
        await manager.authenticate_login(
            request(), (await manager.login(request(), "root@example.test", "pw-1234")).token
        )
    )
    await operator.delete_org(admin, org.id)
    _, again = await manager.bootstrap(
        request(), "Acme", "acme", "bob@example.test", "pw-1234", "Bob"
    )
    assert again.id != org.id and again.slug == "acme"
    with pytest.raises(Conflict):
        await manager.bootstrap(request(), "Acme 3", "acme", "cat@example.test", "pw-1234", "Cat")


async def test_login_rejects_a_wrong_password(manager: TenancyManagerImpl) -> None:
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    with pytest.raises(InvalidCredential):
        await manager.login(request(), "ann@example.test", "nope")
    with pytest.raises(InvalidCredential):
        await manager.login(request(), "nobody@example.test", "pw-1234")


async def test_an_unknown_email_costs_a_password_check_off_the_event_loop(
    manager: TenancyManagerImpl, monkeypatch: pytest.MonkeyPatch
) -> None:
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    calls: list[tuple[str, str, bool]] = []

    def recording(password: str, stored: str) -> bool:
        calls.append((password, stored, threading.current_thread() is threading.main_thread()))
        return verify_password(password, stored)

    monkeypatch.setattr("tadas.om.tenancy.impl.manager.verify_password", recording)
    with pytest.raises(InvalidCredential):
        await manager.login(request(), "nobody@example.test", "pw-1234")
    # Verified once, against the dummy, and not on the loop's thread.
    assert [(p, s) for p, s, _ in calls] == [("pw-1234", DUMMY_PASSWORD_HASH)]
    assert calls[0][2] is False
    assert DUMMY_PASSWORD_HASH.startswith("scrypt$")
    assert not verify_password("pw-1234", DUMMY_PASSWORD_HASH)
    # A known email verifies against its own hash, off the loop as well.
    await manager.login(request(), "ann@example.test", "pw-1234")
    assert calls[1][1] != DUMMY_PASSWORD_HASH and calls[1][2] is False


async def test_a_login_credential_cannot_call_tenant_routes(manager: TenancyManagerImpl) -> None:
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    with pytest.raises(InvalidCredential):
        await manager.authenticate(request(), login.token)
    with pytest.raises(InvalidCredential):
        await manager.authenticate(request(), "garbage")


async def test_exchange_needs_a_membership_in_that_org(manager: TenancyManagerImpl) -> None:
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    _, other = await manager.bootstrap(
        request(), "Beta", "beta", "bob@example.test", "pw-1234", "Bob"
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    with pytest.raises(NotAuthorized):
        await manager.exchange_login(
            await manager.authenticate_login(request(), login.token), other.id
        )


async def test_exchange_refuses_a_gone_org_or_membership_as_not_authorized(
    manager: TenancyManagerImpl,
    storage: TenancyStorageMemoryImpl,
    operator: TenancyOperatorManagerImpl,
) -> None:
    # The sign-in is good; the tenant is not one the identity can enter. A 401
    # would make both clients discard a valid login, so it is a 403, as the
    # interface says.
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    bob = await add_member(storage, org.id, "bob@example.test", Role.MEMBER)
    ended = await storage.read_membership_for_user(org.id, bob.id)
    assert ended is not None
    await storage.write_membership(
        org.id, ended.model_copy(update={"deleted_at": utcnow(), "deleted_by": org.created_by})
    )
    login = await manager.login(request(), "bob@example.test", "pw-1234")
    with pytest.raises(NotAuthorized):
        await manager.exchange_login(
            await manager.authenticate_login(request(), login.token), org.id
        )

    await manager.bootstrap(
        request(),
        "Ops",
        "ops",
        "root@example.test",
        "pw-1234",
        "Root",
        operator_role=OperatorRole.WRITE,
    )
    admin = await manager.admit_operator(
        await manager.authenticate_login(
            request(), (await manager.login(request(), "root@example.test", "pw-1234")).token
        )
    )
    await operator.delete_org(admin, org.id)
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    identity = await manager.authenticate_login(request(), login.token)
    with pytest.raises(NotAuthorized):
        await manager.exchange_login(identity, org.id)
    # The login itself still stands.
    assert (
        await manager.authenticate_login(request(), login.token)
    ).identity_id == identity.identity_id


async def test_expired_sessions_are_refused(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    manager = make_manager(storage, infra, TenancyOptions(session_ttl=timedelta(seconds=-1)))
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    issued = await manager.exchange_login(
        await manager.authenticate_login(request(), login.token), org.id
    )
    with pytest.raises(CredentialExpired):
        await manager.authenticate(request(), issued.token)


async def test_api_keys_are_role_capped_and_revocable(
    manager: TenancyManagerImpl, infra: InfraLocalImpl
) -> None:
    seen: list[TopicPayload] = []

    async def record(payload: TopicPayload) -> None:
        seen.append(payload)

    infra.get_topics().subscribe(Topics.ENTITY_CHANGED, "test", record)
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)

    issued = await manager.create_api_key(owner, "ci", Role.MEMBER)
    key_ctx = await manager.authenticate(
        request(AppContext(type=AppType.CLI, version="cli@0")), issued.key
    )
    assert key_ctx.security.role is Role.MEMBER
    assert key_ctx.security.credential_kind is CredentialKind.API_KEY
    assert not key_ctx.has(Permission.MANAGE_MEMBERS)

    # An api key mints nothing, at its own role or above: revoking a leaked key
    # has to end the access it gave, and a successor would outlive it.
    for role in (Role.MEMBER, Role.OWNER):
        with pytest.raises(NotAuthorized):
            await manager.create_api_key(key_ctx, "successor", role)
    assert [k.id for k in (await manager.get_api_keys(owner, None, limit=10)).items] == [
        issued.api_key.id
    ]
    revoked = await manager.revoke_api_key(owner, issued.api_key.id)
    assert revoked.deleted_at is not None
    with pytest.raises(CredentialExpired):
        await manager.authenticate(request(), issued.key)
    assert [type(p) for p in seen] == [EntityChangedPayload, EntityChangedPayload]
    assert all(p.org_id == org.id for p in seen)


async def test_no_one_mints_a_service_key(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl
) -> None:
    # The service role holds MANAGE_MEMBERS and a member does not; it is refused
    # by name before the ladder is asked, for the owner as for the member.
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    await add_member(storage, org.id, "bob@example.test", Role.MEMBER)
    owner = await sign_in(manager, "ann@example.test", org.id)
    member = await sign_in(manager, "bob@example.test", org.id)
    assert not member.has(Permission.MANAGE_MEMBERS)
    for ctx in (member, owner):
        with pytest.raises(ValidationFailed):
            await manager.create_api_key(ctx, "svc", Role.SERVICE)
    assert (await manager.get_api_keys(owner, None, limit=10)).items == ()


async def test_a_rerun_of_the_create_reissues_the_secret_on_the_same_key(
    manager: TenancyManagerImpl, infra: InfraLocalImpl, markers: IdempotencyStorageMemoryImpl
) -> None:
    seen: list[TopicPayload] = []

    async def record(payload: TopicPayload) -> None:
        seen.append(payload)

    infra.get_topics().subscribe(Topics.ENTITY_CHANGED, "test", record)
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)
    api_key_id = new_id()
    attempt = await begin_attempt(markers, owner, "retried", api_key_id)
    first = await manager.create_api_key(owner, "ci", Role.MEMBER, attempt=attempt)
    assert (await manager.authenticate(request(), first.key)).credential_id == api_key_id

    # The retry that took over an abandoned marker runs the create again on
    # the id the marker carries: same row, fresh secret, and the first secret,
    # which reached no one, stops authenticating.
    taken = await markers.take_over_pending(
        owner.org_id, owner.user_id, "retried", lease_bound(utcnow()), new_id()
    )
    assert taken is not None and taken.attempt_id is not None
    retry = Attempt(target_id=taken.target_id, attempt_id=taken.attempt_id)
    again = await manager.create_api_key(owner, "ci", Role.MEMBER, attempt=retry)
    assert again.key != first.key
    assert again.api_key.id == api_key_id
    assert again.api_key.created_at == first.api_key.created_at
    assert (await manager.authenticate(request(), again.key)).credential_id == api_key_id
    with pytest.raises(InvalidCredential):
        await manager.authenticate(request(), first.key)
    assert [k.id for k in (await manager.get_api_keys(owner, None, limit=10)).items] == [api_key_id]
    assert len(seen) == 1, "the key was announced once"

    # The attempt the retry took the marker from is a zombie: its re-mint is
    # refused, and the secret the caller is holding goes on authenticating.
    with pytest.raises(Conflict):
        await manager.create_api_key(owner, "ci", Role.MEMBER, attempt=attempt)
    assert (await manager.authenticate(request(), again.key)).credential_id == api_key_id


async def test_api_key_ttl_is_bounded_by_the_option(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    manager = make_manager(storage, infra, TenancyOptions(api_key_ttl=timedelta(days=30)))
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)

    with pytest.raises(ValidationFailed):
        await manager.create_api_key(owner, "too-long", Role.MEMBER, timedelta(days=31))
    with pytest.raises(ValidationFailed):
        await manager.create_api_key(owner, "instant", Role.MEMBER, timedelta(0))
    issued = await manager.create_api_key(owner, "short", Role.MEMBER, timedelta(days=7))
    assert issued.api_key.expires_at - issued.api_key.created_at == timedelta(days=7)
    default = await manager.create_api_key(owner, "default", Role.MEMBER)
    assert default.api_key.expires_at - default.api_key.created_at == timedelta(days=30)


async def test_member_roles_are_capped_at_the_callers_role(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)
    bob = await add_member(storage, org.id, "bob@example.test", Role.ADMIN)
    cid = await add_member(storage, org.id, "cid@example.test", Role.VIEWER)
    admin = await sign_in(manager, "bob@example.test", org.id)

    promoted = await manager.update_membership_role(admin, cid.id, Role.MEMBER)
    assert promoted.role is Role.MEMBER
    assert promoted.updated_at > promoted.created_at
    assert (await sign_in(manager, "cid@example.test", org.id)).security.role is Role.MEMBER

    with pytest.raises(NotAuthorized):
        await manager.update_membership_role(admin, cid.id, Role.OWNER)
    with pytest.raises(NotAuthorized):
        await manager.update_membership_role(admin, owner.user_id, Role.VIEWER)
    with pytest.raises(ValidationFailed):
        await manager.update_membership_role(admin, bob.id, Role.MEMBER)
    with pytest.raises(ValidationFailed):
        await manager.update_membership_role(owner, cid.id, Role.SERVICE)
    with pytest.raises(NotFound):
        await manager.update_membership_role(owner, new_id(), Role.MEMBER)
    member = await sign_in(manager, "cid@example.test", org.id)
    with pytest.raises(NotAuthorized):
        await manager.update_membership_role(member, bob.id, Role.VIEWER)


async def test_removing_a_member_soft_deletes_the_user_and_ends_access(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)
    bob = await add_member(storage, org.id, "bob@example.test", Role.ADMIN)
    cid = await add_member(storage, org.id, "cid@example.test", Role.MEMBER)
    admin = await sign_in(manager, "bob@example.test", org.id)
    cid_login = await manager.login(request(), "cid@example.test", "pw-1234")
    cid_session = await manager.exchange_login(
        await manager.authenticate_login(request(), cid_login.token), org.id
    )
    member = await manager.authenticate(request(), cid_session.token)

    with pytest.raises(NotAuthorized):
        await manager.remove_member(admin, owner.user_id)
    with pytest.raises(ValidationFailed):
        await manager.remove_member(admin, bob.id)
    with pytest.raises(NotAuthorized):
        await manager.remove_member(member, bob.id)

    removed = await manager.remove_member(admin, cid.id)
    assert removed.deleted_at is not None and removed.deleted_by == admin.user_id
    assert removed.updated_at == removed.deleted_at
    assert [u.id for u in (await manager.get_users(owner, None, limit=10)).items] == sorted(
        [owner.user_id, bob.id]
    )
    with pytest.raises(CredentialExpired):  # revoked with the member
        await manager.authenticate(request(), cid_session.token)
    assert (await manager.login(request(), "cid@example.test", "pw-1234")).memberships == ()
    with pytest.raises(NotFound):
        await manager.remove_member(admin, cid.id)
    # The membership ended with the member: no list shows it, no role change reaches it.
    assert [m.user_id for m in await manager.get_memberships(owner, limit=10)] == sorted(
        [owner.user_id, bob.id]
    )
    with pytest.raises(NotFound):
        await manager.update_membership_role(owner, cid.id, Role.VIEWER)
    ended = await storage.read_membership_for_user(org.id, cid.id)
    assert ended is None


async def test_removing_a_member_revokes_their_credentials_and_announces_each(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    relay = SpyRelay(OutboxRelayImpl(outbox, EventStorageMemoryImpl(), infra.get_topics()))
    manager = TenancyManagerImpl(
        storage, relay, infra.get_cache(CacheScope.REALTIME_TICKET), TenancyOptions()
    )
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)
    bob = await add_member(storage, org.id, "bob@example.test", Role.MEMBER)
    bobs = await sign_in(manager, "bob@example.test", org.id)
    other = await sign_in(manager, "bob@example.test", org.id)
    key = await manager.create_api_key(bobs, "ci", Role.MEMBER)
    assert key.api_key.id in [
        k.id for k in (await manager.get_api_keys(owner, None, limit=10)).items
    ]

    await manager.remove_member(owner, bob.id)
    # No key of theirs stays listed for a manager, and no session of theirs is live.
    assert [k.user_id for k in (await manager.get_api_keys(owner, None, limit=10)).items] == []
    assert await storage.read_sessions(org.id, bob.id, utcnow(), 10) == []
    stored = await storage.read_api_key(org.id, key.api_key.id)
    assert stored is not None and stored.deleted_at is not None
    assert stored.deleted_by == owner.user_id
    # The removal is announced first, so their sockets close as a membership
    # that ended; then each revocation, the way a revocation is.
    kinds = [(r.kind, r.target_id) for _, r in relay.rows if r.actor_id == owner.user_id]
    assert kinds[0] == ("tenancy.user.deleted", bob.id)
    assert sorted(kinds[1:]) == sorted(
        [
            ("tenancy.session.revoked", bobs.security.credential_id),
            ("tenancy.session.revoked", other.security.credential_id),
            ("tenancy.api_key.deleted", key.api_key.id),
        ]
    )
    assert await claim_all(outbox) == []


async def test_no_event_about_a_user_carries_who_they_are(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    """The stream outlives a removed member; the purge that erases a person
    reaches the user row and not the stream, so the stream never holds the
    email or the name."""
    relay = SpyRelay(OutboxRelayImpl(outbox, EventStorageMemoryImpl(), infra.get_topics()))
    manager = TenancyManagerImpl(
        storage, relay, infra.get_cache(CacheScope.REALTIME_TICKET), TenancyOptions()
    )
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)
    _, bob, _ = await manager.add_member(
        request(), "acme", "bob@example.test", "pw-1234", "Bob", Role.MEMBER
    )
    await manager.remove_member(owner, bob.id)
    about_users = [r for _, r in relay.rows if r.kind.startswith("tenancy.user.")]
    assert [r.kind for r in about_users] == ["tenancy.user.created", "tenancy.user.deleted"]
    for row in about_users:
        assert not PERSONAL_FIELDS & set(row.payload), row.kind
        assert row.payload["identity_id"] == str(bob.identity_id)


class DownOnRemoveStorage(TenancyStorageMemoryImpl):
    """The writes that end a member fail while `down`: the twin of a database
    that went away between two statements."""

    down = True

    async def write_user(
        self, org_id: UUID, user: User, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        if self.down and user.deleted_at is not None:
            raise RuntimeError("storage is down")
        await super().write_user(org_id, user, outbox_rows)

    async def remove_member(
        self, org_id: UUID, user: User, membership: Membership, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        if self.down:
            raise RuntimeError("storage is down")
        await super().remove_member(org_id, user, membership, outbox_rows)


async def test_a_removal_that_fails_leaves_the_member_whole(
    infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    # The user and the membership go in one write: a failure leaves both, so
    # the member is still listed, still a member, and the next remove finishes
    # the job. Their credentials may already be revoked; that is recoverable.
    storage = DownOnRemoveStorage(outbox)
    manager = make_manager(storage, infra, outbox=outbox)
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)
    cid = await add_member(storage, org.id, "cid@example.test", Role.MEMBER)
    with pytest.raises(RuntimeError):
        await manager.remove_member(owner, cid.id)
    assert cid.id in [u.id for u in (await manager.get_users(owner, None, limit=10)).items]
    assert cid.id in [m.user_id for m in await manager.get_memberships(owner, limit=10)]
    _, _, created = await manager.add_member(
        request(), "acme", "cid@example.test", "pw-1234", "Cid", Role.MEMBER
    )
    assert not created, "still a member"
    storage.down = False
    removed = await manager.remove_member(owner, cid.id)
    assert removed.deleted_at is not None
    assert cid.id not in [u.id for u in (await manager.get_users(owner, None, limit=10)).items]
    assert await storage.read_membership_for_user(org.id, cid.id) is None


async def test_a_membership_needs_a_live_user_to_be_read_or_changed(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)
    cid = await add_member(storage, org.id, "cid@example.test", Role.MEMBER)
    # The user row goes while the membership row stays live: the membership is
    # still not one to list or change.
    now = utcnow()
    await storage.write_user(
        org.id, cid.model_copy(update={"deleted_at": now, "deleted_by": owner.user_id})
    )
    with pytest.raises(NotFound):
        await manager.update_membership_role(owner, cid.id, Role.VIEWER)
    with pytest.raises(NotFound):
        await manager.remove_member(owner, cid.id)


async def test_users_update_their_own_display_name(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)
    await add_member(storage, org.id, "cid@example.test", Role.VIEWER)
    viewer = await sign_in(manager, "cid@example.test", org.id)

    # The context carries the user's id; the entity is loaded by the manager.
    me = await manager.get_user(viewer, viewer.user_id)
    renamed = await manager.update_user(viewer, me.model_copy(update={"display_name": "Cid R."}))
    assert renamed.display_name == "Cid R." and renamed.updated_at > renamed.created_at
    assert renamed.updated_by == viewer.user_id
    assert await manager.get_user(viewer, viewer.user_id) == renamed

    with pytest.raises(NotAuthorized):
        owner_user = await manager.get_user(owner, owner.user_id)
        await manager.update_user(viewer, owner_user.model_copy(update={"display_name": "Nope"}))
    with pytest.raises(ValidationFailed):
        await manager.update_user(viewer, me.model_copy(update={"display_name": "  "}))
    by_owner = await manager.update_user(
        owner, renamed.model_copy(update={"display_name": "Cid", "email": "ignored@example.test"})
    )
    assert by_owner.display_name == "Cid" and by_owner.email == "cid@example.test"


async def test_sessions_are_listed_revoked_and_logged_out(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    first = await manager.exchange_login(
        await manager.authenticate_login(request(), login.token), org.id
    )
    second = await manager.exchange_login(
        await manager.authenticate_login(request(), login.token), org.id
    )
    ctx = await manager.authenticate(request(), first.token)
    other = await manager.authenticate(request(), second.token)

    sessions = await manager.get_sessions(ctx, limit=10)
    assert {s.id for s in sessions} == {ctx.security.credential_id, other.security.credential_id}
    assert all(s.credential_kind is CredentialKind.SESSION_TOKEN for s in sessions)

    revoked = await manager.revoke_session(ctx, other.security.credential_id)
    assert revoked.revoked_at is not None and revoked.updated_at == revoked.revoked_at
    with pytest.raises(CredentialExpired):
        await manager.authenticate(request(), second.token)
    assert [s.id for s in await manager.get_sessions(ctx, limit=10)] == [ctx.security.credential_id]
    with pytest.raises(NotFound):
        await manager.revoke_session(ctx, other.security.credential_id)

    await add_member(storage, org.id, "cid@example.test", Role.VIEWER)
    viewer = await sign_in(manager, "cid@example.test", org.id)
    with pytest.raises(NotAuthorized):
        await manager.revoke_session(viewer, ctx.security.credential_id)
    assert await manager.get_sessions(viewer, limit=10) != sessions

    issued = await manager.create_api_key(ctx, "ci", Role.MEMBER)
    key_ctx = await manager.authenticate(request(), issued.key)
    with pytest.raises(ValidationFailed):
        await manager.logout(key_ctx)

    out = await manager.logout(ctx)
    assert out.id == ctx.security.credential_id and out.revoked_at is not None
    with pytest.raises(CredentialExpired):
        await manager.authenticate(request(), first.token)


class SpyRelay(OutboxRelayInterface):
    """The real relay, with every row it was handed kept for the assertions."""

    def __init__(self, relay: OutboxRelayImpl) -> None:
        self._relay = relay
        self.rows: list[tuple[UUID, OutboxRow]] = []

    async def relay(self, org_id: UUID, row: OutboxRow) -> bool:
        self.rows.append((org_id, row))
        return await self._relay.relay(org_id, row)

    async def relay_pending(self, limit: int) -> int:
        return await self._relay.relay_pending(limit)

    async def purge_done(self, retention: timedelta) -> int:
        return await self._relay.purge_done(retention)


async def test_revoking_a_session_announces_it_on_the_bus_without_its_token(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    """The socket that session opened lives in some process; the revocation
    reaches it as any change does, an outbox row the relay publishes. The
    event is a record, not a credential: its snapshot has no token hash."""
    relay = SpyRelay(OutboxRelayImpl(outbox, EventStorageMemoryImpl(), infra.get_topics()))
    manager = TenancyManagerImpl(
        storage, relay, infra.get_cache(CacheScope.REALTIME_TICKET), TenancyOptions()
    )
    published: list[TopicPayload] = []

    async def hear(payload: TopicPayload) -> None:
        published.append(payload)

    infra.get_topics().subscribe(Topics.ENTITY_CHANGED, "test", hear)
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ctx = await sign_in(manager, "ann@example.test", org.id)
    other = await sign_in(manager, "ann@example.test", org.id)

    revoked = await manager.revoke_session(ctx, other.security.credential_id)
    row = next(r for _, r in relay.rows if r.kind == "tenancy.session.revoked")
    assert row.target_id == revoked.id and row.actor_id == ctx.user_id
    assert "token_hash" not in row.payload
    assert row.payload["revoked_at"] is not None and row.payload["user_id"] == str(ctx.user_id)
    frames = [p for p in published if isinstance(p, EntityChangedPayload)]
    assert [(f.kind, f.target_id, f.org_id) for f in frames if f.kind.startswith("tenancy.se")] == [
        ("tenancy.session.revoked", revoked.id, org.id)
    ]

    # Logging out is the same revocation, announced the same way.
    out = await manager.logout(ctx)
    assert [r.target_id for _, r in relay.rows if r.kind == "tenancy.session.revoked"] == [
        revoked.id,
        out.id,
    ]


async def test_a_page_of_dead_sessions_never_hides_a_live_one(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    manager = make_manager(storage, infra, TenancyOptions(max_limit=1), outbox=outbox)
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    ictx = await manager.authenticate_login(request(), login.token)
    older = await manager.authenticate(
        request(), (await manager.exchange_login(ictx, org.id)).token
    )
    newer = await manager.authenticate(
        request(), (await manager.exchange_login(ictx, org.id)).token
    )
    stale = await storage.read_session(org.id, older.security.credential_id)
    assert stale is not None
    await storage.write_session(
        org.id, stale.model_copy(update={"expires_at": utcnow() - timedelta(seconds=1)})
    )
    # The page holds one session; the expired one must not be it.
    assert [s.id for s in await manager.get_sessions(newer, limit=10)] == [
        newer.security.credential_id
    ]


async def test_a_members_own_keys_are_found_behind_a_page_of_others(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    manager = make_manager(storage, infra, TenancyOptions(max_limit=2), outbox=outbox)
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    owner = await sign_in(manager, "ann@example.test", org.id)
    await add_member(storage, org.id, "bob@example.test", Role.MEMBER)
    bob = await sign_in(manager, "bob@example.test", org.id)
    anns = [await manager.create_api_key(owner, "ci", Role.MEMBER) for _ in range(2)]
    own = await manager.create_api_key(bob, "mine", Role.MEMBER)
    # Bob sees his own key though the page is full of Ann's older ones.
    assert [k.id for k in (await manager.get_api_keys(bob, None, limit=10)).items] == [
        own.api_key.id
    ]
    # The member manager sees the tenant's newest page.
    assert [k.id for k in (await manager.get_api_keys(owner, None, limit=10)).items] == [
        own.api_key.id,
        anns[1].api_key.id,
    ]


async def test_the_identity_behind_the_caller(manager: TenancyManagerImpl) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ctx = await sign_in(manager, "ann@example.test", org.id)
    identity = await manager.get_identity(ctx)
    assert identity.id == (await manager.get_user(ctx, ctx.user_id)).identity_id
    assert identity.email == "ann@example.test" and identity.operator_role is None


async def test_operator_gate_admits_only_operators_signing_in(
    manager: TenancyManagerImpl, operator: TenancyOperatorManagerImpl
) -> None:
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    await manager.bootstrap(
        request(),
        "Ops",
        "ops",
        "root@example.test",
        "pw-1234",
        "Root",
        operator_role=OperatorRole.WRITE,
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    with pytest.raises(NotAnOperator):
        await manager.admit_operator(await manager.authenticate_login(request(), login.token))

    operator_login = await manager.login(request(), "root@example.test", "pw-1234")
    identity = await manager.authenticate_login(request(), operator_login.token)
    admin = await manager.admit_operator(identity)
    assert admin.email == "root@example.test"
    assert len(await operator.get_orgs(admin, limit=10)) == 2
    assert len(await operator.get_orgs(admin, limit=1)) == 1

    # A tenant session is not the person's own sign-in: the identity stage refuses it.
    ops_org = next(m.org for m in operator_login.memberships if m.org.slug == "ops")
    session = await manager.exchange_login(identity, ops_org.id)
    with pytest.raises(InvalidCredential):
        await manager.authenticate_login(request(), session.token)


async def test_operators_soft_delete_an_org_and_its_principals_stop_resolving(
    manager: TenancyManagerImpl, operator: TenancyOperatorManagerImpl, infra: InfraLocalImpl
) -> None:
    published: list[TopicPayload] = []

    async def hear(payload: TopicPayload) -> None:
        published.append(payload)

    infra.get_topics().subscribe(Topics.ENTITY_CHANGED, "test", hear)
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    await manager.bootstrap(
        request(),
        "Ops",
        "ops",
        "root@example.test",
        "pw-1234",
        "Root",
        operator_role=OperatorRole.WRITE,
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    issued = await manager.exchange_login(
        await manager.authenticate_login(request(), login.token), org.id
    )
    admin = await manager.admit_operator(
        await manager.authenticate_login(
            request(), (await manager.login(request(), "root@example.test", "pw-1234")).token
        )
    )

    deleted = await operator.delete_org(admin, org.id)
    assert deleted.deleted_at is not None and deleted.deleted_by == admin.identity_id
    assert deleted.updated_at == deleted.deleted_at
    with pytest.raises(InvalidCredential):
        await manager.authenticate(request(), issued.token)
    assert (await manager.login(request(), "ann@example.test", "pw-1234")).memberships == ()
    # The deletion is announced into the tenant's stream, so every socket of
    # the tenant closes, in whichever process holds it; the operator's identity
    # is the actor, since an operator has no user in the tenant.
    frames = [p for p in published if isinstance(p, EntityChangedPayload)]
    assert [(f.kind, f.target_id, f.org_id, f.actor_id) for f in frames if "org" in f.kind] == [
        ("tenancy.org.deleted", org.id, org.id, admin.identity_id)
    ]
    # The sweep still visits the deleted tenant: its rows are the sweep's to purge.
    assert org.id in [c.org_id for c in await manager.service_contexts(request())]
    with pytest.raises(NotFound):
        await operator.delete_org(admin, org.id)
    with pytest.raises(NotFound):
        await operator.delete_org(admin, new_id())


async def test_a_deleted_orgs_rows_are_purged_once_the_retention_has_passed(
    manager: TenancyManagerImpl,
    operator: TenancyOperatorManagerImpl,
    storage: TenancyStorageMemoryImpl,
    infra: InfraLocalImpl,
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ann = await sign_in(manager, "ann@example.test", org.id)
    await manager.create_api_key(ann, "ci", Role.MEMBER)
    await manager.issue_ticket(ann)
    await manager.bootstrap(
        request(),
        "Ops",
        "ops",
        "root@example.test",
        "pw-1234",
        "Root",
        operator_role=OperatorRole.WRITE,
    )
    admin = await manager.admit_operator(
        await manager.authenticate_login(
            request(), (await manager.login(request(), "root@example.test", "pw-1234")).token
        )
    )
    await operator.delete_org(admin, org.id)
    sweep = next(c for c in await manager.service_contexts(request()) if c.org_id == org.id)
    assert sweep.role is Role.SERVICE and sweep.user_id == EMPTY_UUID
    # Within the retention nothing of the tenant is deleted in its own right, so
    # nothing goes; past it, every row of the tenant goes and the org row stays.
    assert await manager.purge_deleted(sweep) == 0
    no_retention = make_manager(storage, infra, TenancyOptions(retention=timedelta(0)))
    assert await no_retention.purge_deleted(sweep) == 5, "user, membership, key, session, ticket"
    assert await storage.read_users(org.id, None, limit=10) == []
    assert await storage.read_memberships(org.id, limit=10) == []
    assert await storage.read_api_keys(org.id, None, limit=10) == []
    assert await storage.read_sessions(org.id, ann.user_id, utcnow(), 10) == []
    tombstone = await storage.read_org(org.id)
    assert tombstone is not None and tombstone.deleted_at is not None
    assert await no_retention.purge_deleted(sweep) == 0


async def test_resume_and_service_contexts(manager: TenancyManagerImpl) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    await manager.bootstrap(request(), "Beta", "beta", "bob@example.test", "pw-1234", "Bob")
    ctx = await sign_in(manager, "ann@example.test", org.id)

    contexts = await manager.service_contexts(request())
    assert len(contexts) == 3, "the system scope, then every tenant"
    assert contexts[0].org_id == EMPTY_UUID
    assert all(c.security.role is Role.SERVICE for c in contexts)
    assert all(c.security.credential_kind is CredentialKind.INTERNAL for c in contexts)
    # Minted for the tenant: the system user is the actor, not the founder.
    assert all(c.user_id == EMPTY_UUID for c in contexts)

    rebuilt = await manager.service_context(request(), org.id, ctx.user_id)
    assert rebuilt.user_id == ctx.user_id
    with pytest.raises(InvalidCredential):
        await manager.resume(request(), org.id, CredentialKind.SESSION_TOKEN, new_id())


async def test_a_claim_for_a_departed_members_item_still_runs_under_their_name(
    manager: TenancyManagerImpl,
    storage: TenancyStorageMemoryImpl,
    operator: TenancyOperatorManagerImpl,
) -> None:
    owner, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ann = await storage.read_user(org.id, owner.user_id)
    assert ann is not None
    now = utcnow()
    await storage.write_user(
        org.id, ann.model_copy(update={"deleted_at": now, "deleted_by": ann.id, "updated_at": now})
    )
    # The person authorized the work at enqueue; the claim keeps them as the
    # attribution and runs on the service role's authority.
    ctx = await manager.service_context(request(), org.id, ann.id)
    assert ctx.user_id == ann.id and ctx.role is Role.SERVICE
    assert ctx.credential_kind is CredentialKind.INTERNAL and ctx.has(Permission.WRITE)
    # Only the tenant must be live.
    await manager.bootstrap(
        request(),
        "Ops",
        "ops",
        "root@example.test",
        "pw-1234",
        "Root",
        operator_role=OperatorRole.WRITE,
    )
    admin = await manager.admit_operator(
        await manager.authenticate_login(
            request(), (await manager.login(request(), "root@example.test", "pw-1234")).token
        )
    )
    await operator.delete_org(admin, org.id)
    with pytest.raises(InvalidCredential):
        await manager.service_context(request(), org.id, ann.id)


async def test_a_tenant_whose_members_have_all_left_is_still_swept(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    owner, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ann = await storage.read_user(org.id, owner.user_id)
    assert ann is not None
    now = utcnow()
    await storage.write_user(
        org.id, ann.model_copy(update={"deleted_at": now, "deleted_by": ann.id, "updated_at": now})
    )
    contexts = await manager.service_contexts(request())
    assert [c.org_id for c in contexts] == [EMPTY_UUID, org.id]
    ctx = contexts[1]
    assert ctx.user_id == EMPTY_UUID and ctx.role is Role.SERVICE
    # The context does the sweep's work: the one member who left is purged.
    assert await manager.purge_deleted(ctx) == 0, "retention has not passed"
    no_retention = make_manager(storage, infra, TenancyOptions(retention=timedelta(0)))
    assert await no_retention.purge_deleted(ctx) == 2, "the user and the membership"
    assert await storage.read_user(org.id, ann.id) is None


async def test_the_sweep_visits_the_system_scope_and_purges_expired_logins(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    # A login credential lives under the system scope, one row per sign-in.
    # The sweep mints a context for that scope too, so the expired ones go
    # the way a tenant's dead sessions do.
    manager = make_manager(storage, infra, TenancyOptions(login_ttl=timedelta(seconds=-1)))
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    found = await storage.read_session_by_token_hash(hash_token(login.token))
    assert found is not None and found[0] == EMPTY_UUID
    system = next(c for c in await manager.service_contexts(request()) if c.org_id == EMPTY_UUID)
    assert system.user_id == EMPTY_UUID and system.role is Role.SERVICE
    assert await manager.purge_deleted(system) == 0, "retention has not passed"
    no_retention = make_manager(storage, infra, TenancyOptions(retention=timedelta(0)))
    assert await no_retention.purge_deleted(system) == 1
    assert await storage.read_session_by_token_hash(hash_token(login.token)) is None


async def test_expired_api_keys_are_purged_like_revoked_ones(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    manager = make_manager(storage, infra, TenancyOptions(api_key_ttl=timedelta(seconds=1)))
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ctx = await sign_in(manager, "ann@example.test", org.id)
    expired = await manager.create_api_key(ctx, "short", Role.MEMBER, ttl=timedelta(seconds=1))
    await asyncio.sleep(1.01)
    assert [k.id for k in (await manager.get_api_keys(ctx, None, limit=10)).items] == [
        expired.api_key.id
    ]
    no_retention = make_manager(storage, infra, TenancyOptions(retention=timedelta(0)))
    sweep = next(c for c in await manager.service_contexts(request()) if c.org_id == org.id)
    assert await no_retention.purge_deleted(sweep) == 1
    assert await storage.read_api_key(org.id, expired.api_key.id) is None


async def test_a_socket_ticket_is_redeemed_exactly_once(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ctx = await sign_in(manager, "ann@example.test", org.id)

    issued = await manager.issue_ticket(ctx)
    assert issued.ticket.startswith("tkt_")
    assert issued.expires_at > utcnow()
    principal = await manager.redeem_ticket(request(), issued.ticket)
    socket_ctx = principal.ctx
    assert socket_ctx.user_id == ctx.user_id
    assert socket_ctx.security.credential_kind is CredentialKind.SOCKET_TICKET
    assert socket_ctx.security.credential_id == ctx.security.credential_id
    # The socket's authority ends with the session behind the ticket.
    session = await storage.read_session(org.id, ctx.security.credential_id)
    assert session is not None and principal.expires_at == session.expires_at
    with pytest.raises(InvalidCredential):
        await manager.redeem_ticket(request(), issued.ticket)
    with pytest.raises(NotAuthorized):
        await manager.issue_ticket(socket_ctx)
    with pytest.raises(InvalidCredential):
        await manager.redeem_ticket(request(), "tkt_never-issued")
    with pytest.raises(InvalidCredential):
        await manager.redeem_ticket(request(), "ses_not-a-ticket")


async def test_concurrent_redemptions_admit_one_socket(manager: TenancyManagerImpl) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ctx = await sign_in(manager, "ann@example.test", org.id)
    issued = await manager.issue_ticket(ctx)

    outcomes = await asyncio.gather(
        *(manager.redeem_ticket(request(), issued.ticket) for _ in range(5)),
        return_exceptions=True,
    )
    admitted = [o for o in outcomes if isinstance(o, SocketPrincipal)]
    refused = [o for o in outcomes if isinstance(o, InvalidCredential)]
    assert len(admitted) == 1 and len(refused) == 4


async def test_the_ticket_row_decides_while_the_cache_is_down(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    manager = make_manager(storage, infra, cache=DownCache())
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ctx = await sign_in(manager, "ann@example.test", org.id)
    issued = await manager.issue_ticket(ctx)
    outcomes = await asyncio.gather(
        *(manager.redeem_ticket(request(), issued.ticket) for _ in range(5)),
        return_exceptions=True,
    )
    assert len([o for o in outcomes if isinstance(o, SocketPrincipal)]) == 1
    assert len([o for o in outcomes if isinstance(o, InvalidCredential)]) == 4
    with pytest.raises(InvalidCredential):
        await manager.redeem_ticket(request(), issued.ticket)
    # The row is spent: the one admitted redeemer consumed it.
    assert await storage.consume_socket_ticket(hash_token(issued.ticket), utcnow()) is None


async def test_redeeming_a_ticket_rechecks_the_credential_behind_it(
    manager: TenancyManagerImpl,
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ctx = await sign_in(manager, "ann@example.test", org.id)
    issued = await manager.issue_ticket(ctx)
    await manager.logout(ctx)
    with pytest.raises(CredentialExpired):
        await manager.redeem_ticket(request(), issued.ticket)

    key = await manager.create_api_key(
        await sign_in(manager, "ann@example.test", org.id), "ci", Role.MEMBER
    )
    key_ctx = await manager.authenticate(request(), key.key)
    from_key = await manager.redeem_ticket(request(), (await manager.issue_ticket(key_ctx)).ticket)
    assert from_key.ctx.security.role is Role.MEMBER
    assert from_key.expires_at == key.api_key.expires_at


async def test_expired_tickets_are_refused(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    manager = make_manager(storage, infra, TenancyOptions(ticket_ttl=timedelta(seconds=-1)))
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ctx = await sign_in(manager, "ann@example.test", org.id)
    issued = await manager.issue_ticket(ctx)
    with pytest.raises(InvalidCredential):
        await manager.redeem_ticket(request(), issued.ticket)


async def test_add_member_seeds_a_second_person_once(manager: TenancyManagerImpl) -> None:
    owner, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    ctx, bob, created = await manager.add_member(
        request(), "acme", "bob@example.test", "pw-1234", "Bob", Role.MEMBER
    )
    assert created and bob.display_name == "Bob"
    # The write ran under the creator's context and is recorded as theirs.
    assert ctx.org_id == org.id and ctx.user_id == owner.user_id
    assert ctx.security.role is Role.OWNER
    assert ctx.security.credential_kind is CredentialKind.INTERNAL
    assert bob.created_by == owner.user_id
    membership = await manager.get_memberships(owner, limit=10)
    assert [(m.user_id, m.created_by) for m in membership if m.user_id == bob.id] == [
        (bob.id, owner.user_id)
    ]
    _, again, created_again = await manager.add_member(
        request(), "acme", "bob@example.test", "other-pw", "Robert", Role.ADMIN
    )
    assert not created_again and again.id == bob.id and again.display_name == "Bob"
    assert sorted(
        u.display_name for u in (await manager.get_users(owner, None, limit=10)).items
    ) == [
        "Ann",
        "Bob",
    ]

    login = await manager.login(
        request(), "bob@example.test", "pw-1234"
    )  # the first password stays
    assert [(m.org.id, m.role) for m in login.memberships] == [(org.id, Role.MEMBER)]
    with pytest.raises(InvalidCredential):
        await manager.login(request(), "bob@example.test", "other-pw")


async def test_add_member_reuses_an_identity_across_orgs(manager: TenancyManagerImpl) -> None:
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    await manager.bootstrap(request(), "Globex", "globex", "gus@example.test", "pw-5678", "Gus")
    _, _, created = await manager.add_member(
        request(), "globex", "ann@example.test", "ignored", "Ann", Role.VIEWER
    )
    assert created
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    assert sorted(m.role.value for m in login.memberships) == ["owner", "viewer"]


async def test_add_member_refuses_an_unknown_org(manager: TenancyManagerImpl) -> None:
    with pytest.raises(NotFound):
        await manager.add_member(
            request(), "nope", "bob@example.test", "pw-1234", "Bob", Role.MEMBER
        )


async def test_add_member_caps_the_role_at_the_creators_and_records_the_write(
    manager: TenancyManagerImpl, infra: InfraLocalImpl
) -> None:
    seen: list[TopicPayload] = []

    async def record(payload: TopicPayload) -> None:
        seen.append(payload)

    infra.get_topics().subscribe(Topics.ENTITY_CHANGED, "test", record)
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    with pytest.raises(ValidationFailed):
        await manager.add_member(
            request(), "acme", "svc@example.test", "pw-1234", "Svc", Role.SERVICE
        )
    ctx, bob, _ = await manager.add_member(
        request(), "acme", "bob@example.test", "pw-1234", "Bob", Role.ADMIN
    )
    pushes = [p for p in seen if isinstance(p, EntityChangedPayload)]
    assert [(p.org_id, p.kind, p.target_id, p.seq) for p in pushes] == [
        (org.id, "tenancy.user.created", bob.id, 1)
    ]
    assert ctx.security.role is Role.OWNER  # the cap: a creator seeds at most their own rank


class RacedIdentityStorage(TenancyStorageMemoryImpl):
    """The read by email misses: another request wrote that identity between
    our read and our write, which is what the unique key is for."""

    async def read_identity_by_email(self, email: str) -> Identity | None:
        return None


async def test_a_duplicate_email_the_read_missed_is_a_conflict_and_leaves_nothing_behind(
    infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    storage = RacedIdentityStorage(outbox)
    manager = make_manager(storage, infra, outbox=outbox)
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    with pytest.raises(UniqueKeyTaken) as raced:
        await manager.bootstrap(request(), "Globex", "globex", "ann@example.test", "pw", "Ann")
    assert (raced.value.http_status, raced.value.code) == (409, "unique_key_taken")
    assert await storage.read_org_by_slug("globex") is None
    with pytest.raises(UniqueKeyTaken) as raced:
        await manager.add_member(request(), "acme", "ann@example.test", "pw", "Ann", Role.MEMBER)
    assert raced.value.http_status == 409
    assert len(await storage.read_users(org.id, None, limit=10)) == 1
    assert len(await storage.read_memberships(org.id, limit=10)) == 1


class RacedSlugStorage(TenancyStorageMemoryImpl):
    """The read by slug misses: another request took the slug between our
    read and our create, which is what the unique key is for."""

    async def read_org_by_slug(self, slug: str) -> Org | None:
        return None


async def test_a_slug_taken_meanwhile_leaves_no_identity_behind(
    infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    storage = RacedSlugStorage(outbox)
    manager = make_manager(storage, infra, outbox=outbox)
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    # A new person: the refused tenant leaves no identity holding this
    # attempt's password, so a retry with another password is not kept out.
    with pytest.raises(UniqueKeyTaken):
        await manager.bootstrap(request(), "Acme 2", "acme", "bob@example.test", "pw-1", "Bob")
    assert await storage.read_identity_by_email("bob@example.test") is None
    _, again = await manager.bootstrap(
        request(), "Bobs", "bobs", "bob@example.test", "pw-1234", "Bob"
    )
    assert again.slug == "bobs"
    assert await sign_in(manager, "bob@example.test", again.id)
    # An existing person asked to be promoted: the refused tenant promotes nobody.
    with pytest.raises(UniqueKeyTaken):
        await manager.bootstrap(
            request(),
            "Ops",
            "acme",
            "ann@example.test",
            "pw-1234",
            "Ann",
            operator_role=OperatorRole.WRITE,
        )
    ann = await storage.read_identity_by_email("ann@example.test")
    assert ann is not None and ann.operator_role is None


class DownOnCreateStorage(TenancyStorageMemoryImpl):
    """The create fails after every read: the twin of a database that went
    away, or a key another request took."""

    async def create_member(
        self,
        org_id: UUID,
        user: User,
        membership: Membership,
        outbox_rows: tuple[OutboxRow, ...],
        identity: Identity | None = None,
    ) -> None:
        raise UniqueKeyTaken("a key is taken")


async def test_an_add_member_that_fails_leaves_no_identity_behind(
    infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    storage = DownOnCreateStorage(outbox)
    manager = make_manager(storage, infra, outbox=outbox)
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    with pytest.raises(UniqueKeyTaken):
        await manager.add_member(request(), "acme", "bob@example.test", "pw-1", "Bob", Role.MEMBER)
    assert await storage.read_identity_by_email("bob@example.test") is None


class RacedUserStorage(TenancyStorageMemoryImpl):
    """The read of the identity's users misses: another request added the same
    person between our read and our write."""

    async def read_users_by_identity(
        self, identity_id: UUID, limit: int
    ) -> list[tuple[UUID, User]]:
        return []


async def test_a_raced_add_member_leaves_no_membership_without_its_user(
    infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    storage = RacedUserStorage(outbox)
    manager = make_manager(storage, infra, outbox=outbox)
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    _, bob, created = await manager.add_member(
        request(), "acme", "bob@example.test", "pw-1234", "Bob", Role.MEMBER
    )
    assert created
    with pytest.raises(UniqueKeyTaken):
        await manager.add_member(request(), "acme", "bob@example.test", "pw", "Bob", Role.ADMIN)
    assert [u.id for u in await storage.read_users(org.id, None, limit=10)] == sorted(
        [bob.id, org.created_by]
    )
    assert sorted(m.user_id for m in await storage.read_memberships(org.id, limit=10)) == sorted(
        [bob.id, org.created_by]
    )
    pending = await outbox.claim_pending(10, utcnow(), timedelta(0), timedelta(0), timedelta(0))
    assert pending == []  # the losing add announced nothing


async def test_every_api_key_is_reachable_a_page_at_a_time(
    manager: TenancyManagerImpl,
) -> None:
    """A list answers a page and says whether another follows; the page a
    caller asks for is a page size, never a ceiling past which a live key
    stops being listed and so cannot be revoked."""
    owner, _ = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    issued = [await manager.create_api_key(owner, f"key-{i}", Role.MEMBER) for i in range(7)]
    newest_first = [k.api_key.id for k in issued][::-1]
    paged: list[UUID] = []
    after: UUID | None = None
    while True:
        page = await manager.get_api_keys(owner, after, limit=3)
        paged += [k.id for k in page.items]
        if not page.has_more:
            break
        after = page.items[-1].id
    assert paged == newest_first
    # The oldest key is on the last page, not lost behind the first.
    last = await manager.get_api_keys(owner, newest_first[-2], limit=3)
    assert [k.id for k in last.items] == [newest_first[-1]] and not last.has_more


async def test_every_member_is_reachable_a_page_at_a_time(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl
) -> None:
    """The member list pages the same way, so the people a task may be
    assigned to are not whatever the first page happened to hold."""
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    for index in range(4):
        await add_member(storage, org.id, f"member-{index}@example.test", Role.MEMBER)
    owner = await sign_in(manager, "ann@example.test", org.id)
    every = sorted(u.id for u in (await manager.get_users(owner, None, limit=50)).items)
    assert len(every) == 5
    paged: list[UUID] = []
    after: UUID | None = None
    while True:
        page = await manager.get_users(owner, after, limit=2)
        paged += [u.id for u in page.items]
        if not page.has_more:
            break
        after = page.items[-1].id
    assert paged == every


async def test_one_person_joins_at_most_the_bound_of_orgs(
    infra: InfraLocalImpl, outbox: OutboxStorageMemoryImpl
) -> None:
    """The users one identity is are read bounded, at one past the orgs a
    person may join. A create that would add one more is refused; a member
    already in the org is still found at the bound; and a list past the bound
    (two adds that raced) is refused, never cut short, since the org a sign-in
    names could be the row cut off."""
    storage = TenancyStorageMemoryImpl(outbox)
    manager = make_manager(storage, infra, TenancyOptions(max_orgs_per_identity=2), outbox=outbox)
    _, first = await manager.bootstrap(request(), "A", "a", "ann@example.test", "pw-1234", "Ann")
    _, second = await manager.bootstrap(request(), "B", "b", "ann@example.test", "pw-1234", "Ann")
    await manager.bootstrap(request(), "C", "c", "cid@example.test", "pw-1234", "Cid")
    with pytest.raises(MembershipLimitReached):
        await manager.bootstrap(request(), "D", "d", "ann@example.test", "pw-1234", "Ann")
    assert await storage.read_org_by_slug("d") is None
    with pytest.raises(MembershipLimitReached):
        await manager.add_member(request(), "c", "ann@example.test", "pw-1234", "Ann", Role.MEMBER)
    _, again, created = await manager.add_member(
        request(), "a", "ann@example.test", "pw-1234", "Ann", Role.MEMBER
    )
    assert not created and again.email == "ann@example.test"
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    assert {m.org.id for m in login.memberships} == {first.id, second.id}

    # A third user lands past the refusal, the way two racing adds would.
    identity = await storage.read_identity_by_email("ann@example.test")
    assert identity is not None
    third = await storage.read_org_by_slug("c")
    assert third is not None
    await storage.write_user(third.id, make_user(identity.id, "ann@example.test"))
    with pytest.raises(MembershipLimitReached):
        await manager.login(request(), "ann@example.test", "pw-1234")
    ictx = await manager.authenticate_login(request(), login.token)
    with pytest.raises(MembershipLimitReached):
        await manager.exchange_login(ictx, first.id)
