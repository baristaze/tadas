import asyncio
import secrets
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest

from tadas.infra.cache import CacheInterface, CacheScope
from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.topics import EntityChangedPayload, TopicPayload, Topics
from tadas.om.base import new_id, utcnow
from tadas.om.events.impl.manager import EventsManagerImpl, EventsOptions
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.exceptions import (
    Conflict,
    CredentialExpired,
    InvalidCredential,
    NotAnOperator,
    NotAuthorized,
    NotFound,
    ValidationFailed,
)
from tadas.om.opcontext import AppContext, AppType, CredentialKind, OpContext, Permission, Role
from tadas.om.tenancy.impl.manager import TenancyManagerImpl, TenancyOptions
from tadas.om.tenancy.rules import hash_password, hash_token
from tadas.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.user import User

APP = AppContext(type=AppType.PORTAL, version="portal@test")


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
def storage() -> TenancyStorageMemoryImpl:
    return TenancyStorageMemoryImpl()


def make_manager(
    storage: TenancyStorageMemoryImpl,
    infra: InfraLocalImpl,
    options: TenancyOptions | None = None,
    cache: CacheInterface | None = None,
) -> TenancyManagerImpl:
    return TenancyManagerImpl(
        storage,
        EventsManagerImpl(EventStorageMemoryImpl(), EventsOptions()),
        infra.get_topics(),
        cache or infra.get_cache(CacheScope.REALTIME_TICKET),
        options or TenancyOptions(),
    )


@pytest.fixture
def manager(storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl) -> TenancyManagerImpl:
    return make_manager(storage, infra)


async def sign_in(manager: TenancyManagerImpl, email: str, org_id: UUID) -> OpContext:
    login = await manager.login(email, "pw-1234")
    issued = await manager.exchange_login(login.token, org_id)
    return await manager.authenticate(issued.token, APP, new_id())


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
            email=email,
            password_hash=hash_password("pw-1234", secrets.token_bytes(16)),
        )
    )
    user = User(
        id=user_id,
        created_at=now,
        updated_at=now,
        created_by=user_id,
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
            user_id=user_id,
            role=role,
        ),
    )
    return user


async def test_bootstrap_produces_the_owners_context(manager: TenancyManagerImpl) -> None:
    ctx, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    assert ctx.org_id == org.id
    assert ctx.security.role is Role.OWNER
    assert ctx.security.credential_kind is CredentialKind.INTERNAL
    assert ctx.app.type is AppType.CLI
    assert (await manager.get_org(ctx)) == org
    assert [u.id for u in await manager.get_users(ctx, limit=10)] == [ctx.user_id]
    issued = await manager.create_api_key(ctx, "seed", Role.MEMBER)
    assert issued.api_key.created_by == ctx.user_id


async def test_bootstrap_login_exchange_authenticate(manager: TenancyManagerImpl) -> None:
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    login = await manager.login("ann@example.test", "pw-1234")
    assert [m.org.id for m in login.memberships] == [org.id]
    assert login.memberships[0].role is Role.OWNER

    issued = await manager.exchange_login(login.token, org.id)
    ctx = await manager.authenticate(issued.token, APP, new_id())
    assert ctx.org_id == org.id
    assert ctx.user_id == issued.user.id
    assert ctx.security.role is Role.OWNER
    assert ctx.security.credential_kind is CredentialKind.SESSION_TOKEN
    assert ctx.has(Permission.MANAGE_MEMBERS)
    assert (await manager.get_org(ctx)) == org
    assert [u.id for u in await manager.get_users(ctx, limit=10)] == [issued.user.id]


async def test_bootstrap_refuses_a_taken_slug(manager: TenancyManagerImpl) -> None:
    await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    with pytest.raises(Conflict):
        await manager.bootstrap("Acme 2", "acme", "bob@example.test", "pw-1234", "Bob")


async def test_login_rejects_a_wrong_password(manager: TenancyManagerImpl) -> None:
    await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    with pytest.raises(InvalidCredential):
        await manager.login("ann@example.test", "nope")
    with pytest.raises(InvalidCredential):
        await manager.login("nobody@example.test", "pw-1234")


async def test_a_login_credential_cannot_call_tenant_routes(manager: TenancyManagerImpl) -> None:
    await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    login = await manager.login("ann@example.test", "pw-1234")
    with pytest.raises(InvalidCredential):
        await manager.authenticate(login.token, APP, new_id())
    with pytest.raises(InvalidCredential):
        await manager.authenticate("garbage", APP, new_id())


async def test_exchange_needs_a_membership_in_that_org(manager: TenancyManagerImpl) -> None:
    await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    _, other = await manager.bootstrap("Beta", "beta", "bob@example.test", "pw-1234", "Bob")
    login = await manager.login("ann@example.test", "pw-1234")
    with pytest.raises(NotAuthorized):
        await manager.exchange_login(login.token, other.id)


async def test_expired_sessions_are_refused(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    manager = make_manager(storage, infra, TenancyOptions(session_ttl=timedelta(seconds=-1)))
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    login = await manager.login("ann@example.test", "pw-1234")
    issued = await manager.exchange_login(login.token, org.id)
    with pytest.raises(CredentialExpired):
        await manager.authenticate(issued.token, APP, new_id())


async def test_api_keys_are_role_capped_and_revocable(
    manager: TenancyManagerImpl, infra: InfraLocalImpl
) -> None:
    seen: list[TopicPayload] = []

    async def record(payload: TopicPayload) -> None:
        seen.append(payload)

    infra.get_topics().subscribe(Topics.ENTITY_CHANGED, "test", record)
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    owner = await sign_in(manager, "ann@example.test", org.id)

    issued = await manager.create_api_key(owner, "ci", Role.MEMBER)
    key_ctx = await manager.authenticate(
        issued.key, AppContext(type=AppType.CLI, version="cli@0"), new_id()
    )
    assert key_ctx.security.role is Role.MEMBER
    assert key_ctx.security.credential_kind is CredentialKind.API_KEY
    assert not key_ctx.has(Permission.MANAGE_MEMBERS)

    with pytest.raises(NotAuthorized):
        await manager.create_api_key(key_ctx, "escalate", Role.OWNER)

    assert [k.id for k in await manager.get_api_keys(owner, limit=10)] == [issued.api_key.id]
    revoked = await manager.revoke_api_key(owner, issued.api_key.id)
    assert revoked.deleted_at is not None
    with pytest.raises(CredentialExpired):
        await manager.authenticate(issued.key, APP, new_id())
    assert [type(p) for p in seen] == [EntityChangedPayload, EntityChangedPayload]
    assert all(p.org_id == org.id for p in seen)


async def test_api_key_ttl_is_bounded_by_the_option(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    manager = make_manager(storage, infra, TenancyOptions(api_key_ttl=timedelta(days=30)))
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
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
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
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
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    owner = await sign_in(manager, "ann@example.test", org.id)
    bob = await add_member(storage, org.id, "bob@example.test", Role.ADMIN)
    cid = await add_member(storage, org.id, "cid@example.test", Role.MEMBER)
    admin = await sign_in(manager, "bob@example.test", org.id)
    cid_login = await manager.login("cid@example.test", "pw-1234")
    cid_session = await manager.exchange_login(cid_login.token, org.id)
    member = await manager.authenticate(cid_session.token, APP, new_id())

    with pytest.raises(NotAuthorized):
        await manager.remove_member(admin, owner.user_id)
    with pytest.raises(ValidationFailed):
        await manager.remove_member(admin, bob.id)
    with pytest.raises(NotAuthorized):
        await manager.remove_member(member, bob.id)

    removed = await manager.remove_member(admin, cid.id)
    assert removed.deleted_at is not None and removed.deleted_by == admin.user_id
    assert removed.updated_at == removed.deleted_at
    assert [u.id for u in await manager.get_users(owner, limit=10)] == sorted(
        [owner.user_id, bob.id]
    )
    with pytest.raises(InvalidCredential):
        await manager.authenticate(cid_session.token, APP, new_id())
    assert (await manager.login("cid@example.test", "pw-1234")).memberships == ()
    with pytest.raises(NotFound):
        await manager.remove_member(admin, cid.id)


async def test_users_update_their_own_display_name(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl
) -> None:
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    owner = await sign_in(manager, "ann@example.test", org.id)
    await add_member(storage, org.id, "cid@example.test", Role.VIEWER)
    viewer = await sign_in(manager, "cid@example.test", org.id)

    renamed = await manager.update_user(
        viewer, viewer.security.user.model_copy(update={"display_name": "Cid R."})
    )
    assert renamed.display_name == "Cid R." and renamed.updated_at > renamed.created_at
    assert (await sign_in(manager, "cid@example.test", org.id)).security.user == renamed

    with pytest.raises(NotAuthorized):
        await manager.update_user(
            viewer, owner.security.user.model_copy(update={"display_name": "Nope"})
        )
    with pytest.raises(ValidationFailed):
        await manager.update_user(
            viewer, viewer.security.user.model_copy(update={"display_name": "  "})
        )
    by_owner = await manager.update_user(
        owner, renamed.model_copy(update={"display_name": "Cid", "email": "ignored@example.test"})
    )
    assert by_owner.display_name == "Cid" and by_owner.email == "cid@example.test"


async def test_sessions_are_listed_revoked_and_logged_out(
    manager: TenancyManagerImpl, storage: TenancyStorageMemoryImpl
) -> None:
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    login = await manager.login("ann@example.test", "pw-1234")
    first = await manager.exchange_login(login.token, org.id)
    second = await manager.exchange_login(login.token, org.id)
    ctx = await manager.authenticate(first.token, APP, new_id())
    other = await manager.authenticate(second.token, APP, new_id())

    sessions = await manager.get_sessions(ctx, limit=10)
    assert {s.id for s in sessions} == {ctx.security.credential_id, other.security.credential_id}
    assert all(s.credential_kind is CredentialKind.SESSION_TOKEN for s in sessions)

    revoked = await manager.revoke_session(ctx, other.security.credential_id)
    assert revoked.revoked_at is not None and revoked.updated_at == revoked.revoked_at
    with pytest.raises(CredentialExpired):
        await manager.authenticate(second.token, APP, new_id())
    assert [s.id for s in await manager.get_sessions(ctx, limit=10)] == [ctx.security.credential_id]
    with pytest.raises(NotFound):
        await manager.revoke_session(ctx, other.security.credential_id)

    await add_member(storage, org.id, "cid@example.test", Role.VIEWER)
    viewer = await sign_in(manager, "cid@example.test", org.id)
    with pytest.raises(NotAuthorized):
        await manager.revoke_session(viewer, ctx.security.credential_id)
    assert await manager.get_sessions(viewer, limit=10) != sessions

    issued = await manager.create_api_key(ctx, "ci", Role.MEMBER)
    key_ctx = await manager.authenticate(issued.key, APP, new_id())
    with pytest.raises(ValidationFailed):
        await manager.logout(key_ctx)

    out = await manager.logout(ctx)
    assert out.id == ctx.security.credential_id and out.revoked_at is not None
    with pytest.raises(CredentialExpired):
        await manager.authenticate(first.token, APP, new_id())


async def test_the_identity_behind_the_caller(manager: TenancyManagerImpl) -> None:
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    ctx = await sign_in(manager, "ann@example.test", org.id)
    identity = await manager.get_identity(ctx)
    assert identity.id == ctx.security.user.identity_id
    assert identity.email == "ann@example.test" and identity.is_operator is False


async def test_operator_gate_admits_only_operators_signing_in(
    manager: TenancyManagerImpl,
) -> None:
    await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    await manager.bootstrap("Ops", "ops", "root@example.test", "pw-1234", "Root", operator=True)
    login = await manager.login("ann@example.test", "pw-1234")
    with pytest.raises(NotAnOperator):
        await manager.authenticate_operator(login.token, new_id())

    operator_login = await manager.login("root@example.test", "pw-1234")
    admin = await manager.authenticate_operator(operator_login.token, new_id())
    assert admin.email == "root@example.test"
    assert len(await manager.get_orgs(admin, limit=10)) == 2

    ops_org = next(m.org for m in operator_login.memberships if m.org.slug == "ops")
    session = await manager.exchange_login(operator_login.token, ops_org.id)
    with pytest.raises(InvalidCredential):
        await manager.authenticate_operator(session.token, new_id())


async def test_operators_soft_delete_an_org_and_its_principals_stop_resolving(
    manager: TenancyManagerImpl,
) -> None:
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    await manager.bootstrap("Ops", "ops", "root@example.test", "pw-1234", "Root", operator=True)
    login = await manager.login("ann@example.test", "pw-1234")
    issued = await manager.exchange_login(login.token, org.id)
    admin = await manager.authenticate_operator(
        (await manager.login("root@example.test", "pw-1234")).token, new_id()
    )

    deleted = await manager.delete_org(admin, org.id)
    assert deleted.deleted_at is not None and deleted.deleted_by == admin.identity_id
    assert deleted.updated_at == deleted.deleted_at
    with pytest.raises(InvalidCredential):
        await manager.authenticate(issued.token, APP, new_id())
    assert (await manager.login("ann@example.test", "pw-1234")).memberships == ()
    assert [c.org_id for c in await manager.service_contexts(APP, new_id())] != [org.id]
    with pytest.raises(NotFound):
        await manager.delete_org(admin, org.id)
    with pytest.raises(NotFound):
        await manager.delete_org(admin, new_id())


async def test_resume_and_service_contexts(manager: TenancyManagerImpl) -> None:
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    await manager.bootstrap("Beta", "beta", "bob@example.test", "pw-1234", "Bob")
    ctx = await sign_in(manager, "ann@example.test", org.id)

    contexts = await manager.service_contexts(APP, new_id())
    assert len(contexts) == 2
    assert all(c.security.role is Role.SERVICE for c in contexts)
    assert all(c.security.credential_kind is CredentialKind.INTERNAL for c in contexts)

    rebuilt = await manager.service_context(org.id, ctx.user_id, APP, new_id())
    assert rebuilt.user_id == ctx.user_id
    with pytest.raises(InvalidCredential):
        await manager.resume(org.id, CredentialKind.SESSION_TOKEN, new_id(), APP, new_id())


async def test_a_socket_ticket_is_redeemed_exactly_once(manager: TenancyManagerImpl) -> None:
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    ctx = await sign_in(manager, "ann@example.test", org.id)

    issued = await manager.issue_ticket(ctx)
    assert issued.ticket.startswith("tkt_")
    assert issued.expires_at > utcnow()
    socket_ctx = await manager.redeem_ticket(issued.ticket, APP, new_id())
    assert socket_ctx.user_id == ctx.user_id
    assert socket_ctx.security.credential_kind is CredentialKind.SOCKET_TICKET
    assert socket_ctx.security.credential_id == ctx.security.credential_id
    with pytest.raises(InvalidCredential):
        await manager.redeem_ticket(issued.ticket, APP, new_id())
    with pytest.raises(NotAuthorized):
        await manager.issue_ticket(socket_ctx)
    with pytest.raises(InvalidCredential):
        await manager.redeem_ticket("tkt_never-issued", APP, new_id())
    with pytest.raises(InvalidCredential):
        await manager.redeem_ticket("ses_not-a-ticket", APP, new_id())


async def test_concurrent_redemptions_admit_one_socket(manager: TenancyManagerImpl) -> None:
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    ctx = await sign_in(manager, "ann@example.test", org.id)
    issued = await manager.issue_ticket(ctx)

    outcomes = await asyncio.gather(
        *(manager.redeem_ticket(issued.ticket, APP, new_id()) for _ in range(5)),
        return_exceptions=True,
    )
    admitted = [o for o in outcomes if isinstance(o, OpContext)]
    refused = [o for o in outcomes if isinstance(o, InvalidCredential)]
    assert len(admitted) == 1 and len(refused) == 4


async def test_the_ticket_row_decides_while_the_cache_is_down(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    manager = make_manager(storage, infra, cache=DownCache())
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    ctx = await sign_in(manager, "ann@example.test", org.id)
    issued = await manager.issue_ticket(ctx)
    outcomes = await asyncio.gather(
        *(manager.redeem_ticket(issued.ticket, APP, new_id()) for _ in range(5)),
        return_exceptions=True,
    )
    assert len([o for o in outcomes if isinstance(o, OpContext)]) == 1
    assert len([o for o in outcomes if isinstance(o, InvalidCredential)]) == 4
    with pytest.raises(InvalidCredential):
        await manager.redeem_ticket(issued.ticket, APP, new_id())
    # The row is spent: the one admitted redeemer consumed it.
    assert await storage.consume_socket_ticket(hash_token(issued.ticket), utcnow()) is None


async def test_redeeming_a_ticket_rechecks_the_credential_behind_it(
    manager: TenancyManagerImpl,
) -> None:
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    ctx = await sign_in(manager, "ann@example.test", org.id)
    issued = await manager.issue_ticket(ctx)
    await manager.logout(ctx)
    with pytest.raises(CredentialExpired):
        await manager.redeem_ticket(issued.ticket, APP, new_id())

    key = await manager.create_api_key(
        await sign_in(manager, "ann@example.test", org.id), "ci", Role.MEMBER
    )
    key_ctx = await manager.authenticate(key.key, APP, new_id())
    from_key = await manager.redeem_ticket(
        (await manager.issue_ticket(key_ctx)).ticket, APP, new_id()
    )
    assert from_key.security.role is Role.MEMBER


async def test_expired_tickets_are_refused(
    storage: TenancyStorageMemoryImpl, infra: InfraLocalImpl
) -> None:
    manager = make_manager(storage, infra, TenancyOptions(ticket_ttl=timedelta(seconds=-1)))
    _, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    ctx = await sign_in(manager, "ann@example.test", org.id)
    issued = await manager.issue_ticket(ctx)
    with pytest.raises(InvalidCredential):
        await manager.redeem_ticket(issued.ticket, APP, new_id())


async def test_add_member_seeds_a_second_person_once(manager: TenancyManagerImpl) -> None:
    owner, org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    bob, created = await manager.add_member(
        "acme", "bob@example.test", "pw-1234", "Bob", Role.MEMBER
    )
    assert created and bob.display_name == "Bob"
    again, created_again = await manager.add_member(
        "acme", "bob@example.test", "other-pw", "Robert", Role.ADMIN
    )
    assert not created_again and again.id == bob.id and again.display_name == "Bob"
    assert sorted(u.display_name for u in await manager.get_users(owner, limit=10)) == [
        "Ann",
        "Bob",
    ]

    login = await manager.login("bob@example.test", "pw-1234")  # the first password stays
    assert [(m.org.id, m.role) for m in login.memberships] == [(org.id, Role.MEMBER)]
    with pytest.raises(InvalidCredential):
        await manager.login("bob@example.test", "other-pw")


async def test_add_member_reuses_an_identity_across_orgs(manager: TenancyManagerImpl) -> None:
    await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    await manager.bootstrap("Globex", "globex", "gus@example.test", "pw-5678", "Gus")
    _, created = await manager.add_member(
        "globex", "ann@example.test", "ignored", "Ann", Role.VIEWER
    )
    assert created
    login = await manager.login("ann@example.test", "pw-1234")
    assert sorted(m.role.value for m in login.memberships) == ["owner", "viewer"]


async def test_add_member_refuses_an_unknown_org(manager: TenancyManagerImpl) -> None:
    with pytest.raises(NotFound):
        await manager.add_member("nope", "bob@example.test", "pw-1234", "Bob", Role.MEMBER)
