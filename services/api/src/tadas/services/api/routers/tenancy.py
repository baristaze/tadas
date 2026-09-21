"""Tenancy routes: sign in, choose a tenant, read the principal, manage
members, sessions, and api keys. Every function is one call into the
tenancy service."""

from uuid import UUID

from fastapi import APIRouter, Response

from tadas.services.api.gateway.auth import Ctx, Identity, Rctx
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.gateway.ratelimit import rate_limited
from tadas.services.api.gateway.resolve import TenancyService
from tadas.services.api.types.common import LIMIT_DEFAULT
from tadas.services.api.types.tenancy import (
    AddApiKeyRequest,
    ApiKeyPageView,
    ApiKeyView,
    ExchangeSessionRequest,
    IdentityView,
    IssuedApiKeyView,
    IssuedLoginView,
    IssuedSessionView,
    LoginRequest,
    MembershipPageView,
    MembershipView,
    MeView,
    OrgView,
    SessionView,
    UpdateMembershipRequest,
    UpdateMeRequest,
    UserPageView,
    UserView,
)

router = APIRouter(tags=["tenancy"])


@router.post("/auth/login", response_model=IssuedLoginView, dependencies=[rate_limited("login")])
async def login(rctx: Rctx, tenancy: TenancyService, body: LoginRequest) -> IssuedLoginView:
    return await tenancy.login(rctx, body)


@router.post("/auth/sessions", response_model=IssuedSessionView)
async def exchange_session(
    identity: Identity, tenancy: TenancyService, body: ExchangeSessionRequest
) -> IssuedSessionView:
    return await tenancy.exchange_session(identity, body)


@router.post("/auth/logout", response_model=SessionView)
async def logout(ctx: Ctx, tenancy: TenancyService) -> SessionView:
    return await tenancy.logout(ctx)


@router.get("/me", response_model=MeView)
async def me(ctx: Ctx, tenancy: TenancyService) -> MeView:
    return await tenancy.get_me(ctx)


@router.patch("/me", response_model=UserView)
async def update_me(ctx: Ctx, tenancy: TenancyService, body: UpdateMeRequest) -> UserView:
    return await tenancy.update_me(ctx, body)


@router.get("/me/identity", response_model=IdentityView)
async def my_identity(ctx: Ctx, tenancy: TenancyService) -> IdentityView:
    return await tenancy.get_identity(ctx)


@router.get("/orgs/current", response_model=OrgView)
async def current_org(ctx: Ctx, tenancy: TenancyService) -> OrgView:
    return await tenancy.get_org(ctx)


@router.get("/users", response_model=UserPageView)
async def list_users(
    ctx: Ctx, tenancy: TenancyService, cursor: str | None = None, limit: int = LIMIT_DEFAULT
) -> UserPageView:
    return await tenancy.get_users(ctx, cursor, limit)


@router.get("/memberships", response_model=MembershipPageView)
async def list_memberships(
    ctx: Ctx, tenancy: TenancyService, cursor: str | None = None, limit: int = LIMIT_DEFAULT
) -> MembershipPageView:
    return await tenancy.get_memberships(ctx, cursor, limit)


@router.patch("/memberships/{user_id}", response_model=MembershipView)
async def update_membership(
    ctx: Ctx, tenancy: TenancyService, user_id: UUID, body: UpdateMembershipRequest
) -> MembershipView:
    return await tenancy.update_membership_role(ctx, user_id, body)


@router.delete("/memberships/{user_id}", response_model=UserView)
async def remove_member(ctx: Ctx, tenancy: TenancyService, user_id: UUID) -> UserView:
    return await tenancy.remove_member(ctx, user_id)


@router.get("/sessions", response_model=list[SessionView])
async def list_sessions(
    ctx: Ctx, tenancy: TenancyService, limit: int = LIMIT_DEFAULT
) -> list[SessionView]:
    return await tenancy.get_sessions(ctx, limit)


@router.delete("/sessions/{session_id}", response_model=SessionView)
async def revoke_session(ctx: Ctx, tenancy: TenancyService, session_id: UUID) -> SessionView:
    return await tenancy.revoke_session(ctx, session_id)


@router.get("/api-keys", response_model=ApiKeyPageView)
async def list_api_keys(
    ctx: Ctx, tenancy: TenancyService, cursor: str | None = None, limit: int = LIMIT_DEFAULT
) -> ApiKeyPageView:
    return await tenancy.get_api_keys(ctx, cursor, limit)


@router.post("/api-keys", response_model=IssuedApiKeyView, status_code=201)
async def create_api_key(
    ctx: Ctx, tenancy: TenancyService, body: AddApiKeyRequest, idem: Idem
) -> Response:
    return await idem.run(201, lambda attempt: tenancy.create_api_key(ctx, body, attempt))


@router.delete("/api-keys/{api_key_id}", response_model=ApiKeyView)
async def revoke_api_key(ctx: Ctx, tenancy: TenancyService, api_key_id: UUID) -> ApiKeyView:
    return await tenancy.revoke_api_key(ctx, api_key_id)
