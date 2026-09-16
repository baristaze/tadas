from datetime import timedelta
from pathlib import Path

import pytest

from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.topics import EntityChangedPayload, TopicPayload, Topics
from tadas.om.base import new_id
from tadas.om.exceptions import (
    Conflict,
    CredentialExpired,
    InvalidCredential,
    NotAnOperator,
    NotAuthorized,
)
from tadas.om.opcontext import AppContext, AppType, CredentialKind, Permission, Role
from tadas.om.tenancy.impl.manager import TenancyManagerImpl, TenancyOptions
from tadas.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl

APP = AppContext(type=AppType.PORTAL, version="portal@test")


@pytest.fixture
def infra(tmp_path: Path) -> InfraLocalImpl:
    return InfraLocalImpl(tmp_path)


@pytest.fixture
def manager(infra: InfraLocalImpl) -> TenancyManagerImpl:
    return TenancyManagerImpl(TenancyStorageMemoryImpl(), infra.get_topics(), TenancyOptions())


async def test_bootstrap_login_exchange_authenticate(manager: TenancyManagerImpl) -> None:
    org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
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
    other = await manager.bootstrap("Beta", "beta", "bob@example.test", "pw-1234", "Bob")
    login = await manager.login("ann@example.test", "pw-1234")
    with pytest.raises(NotAuthorized):
        await manager.exchange_login(login.token, other.id)


async def test_expired_sessions_are_refused(infra: InfraLocalImpl) -> None:
    options = TenancyOptions(session_ttl=timedelta(seconds=-1))
    manager = TenancyManagerImpl(TenancyStorageMemoryImpl(), infra.get_topics(), options)
    org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
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
    org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    login = await manager.login("ann@example.test", "pw-1234")
    owner = await manager.authenticate(
        (await manager.exchange_login(login.token, org.id)).token, APP, new_id()
    )

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


async def test_resume_and_service_contexts(manager: TenancyManagerImpl) -> None:
    org = await manager.bootstrap("Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    await manager.bootstrap("Beta", "beta", "bob@example.test", "pw-1234", "Bob")
    login = await manager.login("ann@example.test", "pw-1234")
    issued = await manager.exchange_login(login.token, org.id)
    ctx = await manager.authenticate(issued.token, APP, new_id())

    contexts = await manager.service_contexts(APP, new_id())
    assert len(contexts) == 2
    assert all(c.security.role is Role.SERVICE for c in contexts)
    assert all(c.security.credential_kind is CredentialKind.INTERNAL for c in contexts)

    rebuilt = await manager.service_context(org.id, ctx.user_id, APP, new_id())
    assert rebuilt.user_id == ctx.user_id
    with pytest.raises(InvalidCredential):
        await manager.resume(org.id, CredentialKind.SESSION_TOKEN, new_id(), APP, new_id())
