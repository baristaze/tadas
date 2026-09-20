"""The context model: four stages, each produced only by a transition (an
operation of the tenancy manager, or one that asks it, as the worker's claim
does), and five scopes every stage satisfies structurally."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from tadas.infra.cache import CacheScope
from tadas.infra.impl.local import InfraLocalImpl
from tadas.om.base import EMPTY_UUID, new_id
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.exceptions import InvalidCredential, NotAnOperator, NotAuthorized
from tadas.om.opcontext import (
    ActorScope,
    AppContext,
    AppType,
    CredentialKind,
    CredentialScope,
    IdentityContext,
    OpContext,
    OperatorContext,
    ProvenanceScope,
    RequestContext,
    RequestScope,
    Role,
    TenantScope,
    build_context,
)
from tadas.om.outbox.impl.relay import OutboxRelayImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.tenancy.impl.manager import TenancyManagerImpl, TenancyOptions
from tadas.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl
from tadas.om.tenancy.types.role import permissions_of

APP = AppContext(type=AppType.PORTAL, version="portal@test")


def request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=APP, trace_id="0" * 31 + "1")


@pytest.fixture
def manager(tmp_path: Path) -> TenancyManagerImpl:
    outbox = OutboxStorageMemoryImpl()
    infra = InfraLocalImpl(tmp_path)
    relay = OutboxRelayImpl(outbox, EventStorageMemoryImpl(), infra.get_topics())
    return TenancyManagerImpl(
        TenancyStorageMemoryImpl(outbox),
        relay,
        infra.get_cache(CacheScope.REALTIME_TICKET),
        TenancyOptions(),
    )


# The stages are refinements: a subclass is accepted where its base is asked for.


def test_every_stage_is_a_request_context_and_only_admin_is_an_identity() -> None:
    assert issubclass(IdentityContext, RequestContext)
    assert issubclass(OpContext, RequestContext)
    assert issubclass(OperatorContext, IdentityContext)
    assert not issubclass(OpContext, IdentityContext)
    assert not issubclass(IdentityContext, OpContext)
    assert not issubclass(OperatorContext, OpContext)


def test_a_stage_is_immutable() -> None:
    rctx = request()
    with pytest.raises(ValidationError, match="frozen"):
        rctx.request_id = new_id()  # pyright: ignore[reportAttributeAccessIssue]


# The transitions: each produces its stage and refuses what it must.


async def test_login_then_authenticate_login_produces_the_identity_stage(
    manager: TenancyManagerImpl,
) -> None:
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    rctx = request()
    login = await manager.login(rctx, "ann@example.test", "pw-1234")
    ictx = await manager.authenticate_login(rctx, login.token)
    assert type(ictx) is IdentityContext
    assert ictx.email == "ann@example.test"
    assert ictx.credential_kind is CredentialKind.LOGIN
    assert ictx.credential_id != EMPTY_UUID
    # The identity stage refines the request stage it was minted from.
    assert (ictx.request_id, ictx.app, ictx.trace_id) == (rctx.request_id, rctx.app, rctx.trace_id)


async def test_authenticate_login_refuses_a_session_token_and_an_api_key(
    manager: TenancyManagerImpl,
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    ictx = await manager.authenticate_login(request(), login.token)
    session = await manager.exchange_login(ictx, org.id)
    with pytest.raises(InvalidCredential):
        await manager.authenticate_login(request(), session.token)
    ctx = await manager.authenticate(request(), session.token)
    key = await manager.create_api_key(ctx, "ci", Role.MEMBER)
    with pytest.raises(InvalidCredential):
        await manager.authenticate_login(request(), key.key)
    with pytest.raises(InvalidCredential):
        await manager.authenticate_login(request(), "lgn_never-issued")


async def test_exchange_login_produces_a_session_and_refuses_a_non_member(
    manager: TenancyManagerImpl,
) -> None:
    _, acme = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    _, beta = await manager.bootstrap(
        request(), "Beta", "beta", "bob@example.test", "pw-1234", "Bob"
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    ictx = await manager.authenticate_login(request(), login.token)
    issued = await manager.exchange_login(ictx, acme.id)
    assert issued.org.id == acme.id and issued.role is Role.OWNER
    with pytest.raises(NotAuthorized):
        await manager.exchange_login(ictx, beta.id)


async def test_authenticate_produces_the_tenant_stage_and_refuses_a_login_token(
    manager: TenancyManagerImpl,
) -> None:
    _, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    ictx = await manager.authenticate_login(request(), login.token)
    issued = await manager.exchange_login(ictx, org.id)
    rctx = request()
    ctx = await manager.authenticate(rctx, issued.token)
    assert type(ctx) is OpContext
    assert ctx.org_id == org.id and ctx.security.role is Role.OWNER
    assert ctx.credential_kind is CredentialKind.SESSION_TOKEN
    assert ctx.credential_id != EMPTY_UUID
    assert (ctx.request_id, ctx.app, ctx.trace_id) == (rctx.request_id, rctx.app, rctx.trace_id)
    with pytest.raises(InvalidCredential):
        await manager.authenticate(request(), login.token)


async def test_admit_operator_produces_the_operator_stage_for_operators_only(
    manager: TenancyManagerImpl,
) -> None:
    await manager.bootstrap(request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    await manager.bootstrap(
        request(), "Ops", "ops", "root@example.test", "pw-1234", "Root", operator=True
    )
    login = await manager.login(request(), "ann@example.test", "pw-1234")
    with pytest.raises(NotAnOperator):
        await manager.admit_operator(await manager.authenticate_login(request(), login.token))

    root = await manager.login(request(), "root@example.test", "pw-1234")
    ictx = await manager.authenticate_login(request(), root.token)
    admin = await manager.admit_operator(ictx)
    assert type(admin) is OperatorContext
    assert isinstance(admin, IdentityContext)
    assert (admin.identity_id, admin.email, admin.credential_id) == (
        ictx.identity_id,
        ictx.email,
        ictx.credential_id,
    )
    assert (admin.request_id, admin.app, admin.trace_id) == (
        ictx.request_id,
        ictx.app,
        ictx.trace_id,
    )
    assert not hasattr(admin, "org_id")


async def test_service_and_socket_contexts_refine_the_request_they_are_given(
    manager: TenancyManagerImpl,
) -> None:
    owner, org = await manager.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    rctx = request()
    service = await manager.service_context(rctx, org.id, owner.user_id)
    assert service.security.role is Role.SERVICE and service.request_id == rctx.request_id
    assert [c.request_id for c in await manager.service_contexts(rctx)] == [rctx.request_id]

    login = await manager.login(request(), "ann@example.test", "pw-1234")
    ictx = await manager.authenticate_login(request(), login.token)
    session = await manager.exchange_login(ictx, org.id)
    ctx = await manager.authenticate(request(), session.token)
    ticket = await manager.issue_ticket(ctx)
    socket_request = request()
    socket_ctx = await manager.redeem_ticket(socket_request, ticket.ticket)
    assert socket_ctx.credential_kind is CredentialKind.SOCKET_TICKET
    assert socket_ctx.credential_id == ctx.credential_id
    assert socket_ctx.request_id == socket_request.request_id


def test_build_context_copies_the_request_stage_and_reads_security() -> None:
    rctx = request()
    ctx = build_context(
        rctx,
        user_id=new_id(),
        org_id=new_id(),
        role=Role.MEMBER,
        permissions=permissions_of(Role.MEMBER),
        credential_kind=CredentialKind.API_KEY,
        credential_id=new_id(),
    )
    assert (ctx.request_id, ctx.app, ctx.trace_id) == (rctx.request_id, rctx.app, rctx.trace_id)
    assert ctx.credential_kind is ctx.security.credential_kind
    assert ctx.credential_id == ctx.security.credential_id
    assert ctx.org_id == ctx.security.org_id and ctx.user_id == ctx.security.user_id
    assert ctx.role is ctx.security.role


# The scopes: typed assignments pyright proves, and the runtime reads them.


def test_every_stage_satisfies_the_scopes_it_carries() -> None:
    rctx = request()
    ictx = IdentityContext(
        request_id=rctx.request_id,
        app=rctx.app,
        identity_id=new_id(),
        email="ann@example.test",
        credential_kind=CredentialKind.LOGIN,
        credential_id=new_id(),
    )
    admin = OperatorContext(
        request_id=rctx.request_id,
        app=rctx.app,
        identity_id=ictx.identity_id,
        email=ictx.email,
        credential_kind=ictx.credential_kind,
        credential_id=ictx.credential_id,
    )
    ctx = build_context(
        rctx,
        user_id=new_id(),
        org_id=new_id(),
        role=Role.MEMBER,
        permissions=permissions_of(Role.MEMBER),
        credential_kind=CredentialKind.SESSION_TOKEN,
        credential_id=new_id(),
    )

    # Every stage is a RequestScope.
    request_scopes: list[RequestScope] = [rctx, ictx, ctx, admin]
    assert [s.request_id for s in request_scopes] == [rctx.request_id] * 4
    assert all(s.app == APP for s in request_scopes)

    # The identity and operator stages carry a credential.
    credential_scopes: list[CredentialScope] = [ictx, admin, ctx]
    assert [s.credential_kind for s in credential_scopes] == [
        CredentialKind.LOGIN,
        CredentialKind.LOGIN,
        CredentialKind.SESSION_TOKEN,
    ]
    assert credential_scopes[0].credential_id == ictx.credential_id

    # The tenant stage satisfies all five.
    tenant: TenantScope = ctx
    actor: ActorScope = ctx
    provenance: ProvenanceScope = ctx
    assert tenant.org_id == ctx.security.org_id
    assert actor.user_id == ctx.security.user_id
    assert (provenance.user_id, provenance.org_id, provenance.request_id, provenance.app) == (
        ctx.user_id,
        ctx.org_id,
        ctx.request_id,
        ctx.app,
    )
