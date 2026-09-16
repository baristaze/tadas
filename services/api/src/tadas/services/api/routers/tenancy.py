"""Tenancy routes: sign in, choose a tenant, read the principal, manage api
keys. Every function translates and calls one manager operation."""

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Request, Response

from tadas.services.api.gateway.auth import Ctx, LoginCredential
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.gateway.ratelimit import rate_limited
from tadas.services.api.types.common import LIMIT_DEFAULT, clamp_limit
from tadas.services.api.types.tenancy import (
    AddApiKeyRequest,
    ApiKeyView,
    ExchangeSessionRequest,
    IssuedApiKeyView,
    IssuedLoginView,
    IssuedSessionView,
    LoginRequest,
    MembershipChoiceView,
    MembershipView,
    MeView,
    OrgView,
    UserView,
)

router = APIRouter(tags=["tenancy"])


def _tenancy(request: Request):
    return request.app.state.container.managers.tenancy


@router.post(
    "/auth/login",
    response_model=IssuedLoginView,
    dependencies=[rate_limited("login", 10, timedelta(minutes=1))],
)
async def login(request: Request, body: LoginRequest) -> IssuedLoginView:
    issued = await _tenancy(request).login(body.email, body.password)
    return IssuedLoginView(
        token=issued.token,
        expires_at=issued.expires_at,
        memberships=[MembershipChoiceView.model_validate(m) for m in issued.memberships],
    )


@router.post("/auth/sessions", response_model=IssuedSessionView)
async def exchange_session(
    request: Request, credential: LoginCredential, body: ExchangeSessionRequest
) -> IssuedSessionView:
    issued = await _tenancy(request).exchange_login(credential, body.org_id)
    return IssuedSessionView.model_validate(issued)


@router.get("/me", response_model=MeView)
async def me(request: Request, ctx: Ctx) -> MeView:
    org = await _tenancy(request).get_org(ctx)
    return MeView(
        user=UserView.model_validate(ctx.security.user),
        org=OrgView.model_validate(org),
        role=ctx.security.role,
        permissions=ctx.security.permissions,
        app=ctx.app.type.value,
    )


@router.get("/orgs/current", response_model=OrgView)
async def current_org(request: Request, ctx: Ctx) -> OrgView:
    return OrgView.model_validate(await _tenancy(request).get_org(ctx))


@router.get("/users", response_model=list[UserView])
async def list_users(request: Request, ctx: Ctx, limit: int = LIMIT_DEFAULT) -> list[UserView]:
    users = await _tenancy(request).get_users(ctx, clamp_limit(limit))
    return [UserView.model_validate(u) for u in users]


@router.get("/memberships", response_model=list[MembershipView])
async def list_memberships(
    request: Request, ctx: Ctx, limit: int = LIMIT_DEFAULT
) -> list[MembershipView]:
    memberships = await _tenancy(request).get_memberships(ctx, clamp_limit(limit))
    return [MembershipView.model_validate(m) for m in memberships]


@router.get("/api-keys", response_model=list[ApiKeyView])
async def list_api_keys(request: Request, ctx: Ctx, limit: int = LIMIT_DEFAULT) -> list[ApiKeyView]:
    keys = await _tenancy(request).get_api_keys(ctx, clamp_limit(limit))
    return [ApiKeyView.model_validate(k) for k in keys]


@router.post("/api-keys", response_model=IssuedApiKeyView, status_code=201)
async def create_api_key(
    request: Request, ctx: Ctx, body: AddApiKeyRequest, idem: Idem
) -> Response:
    if (replay := await idem.replay()) is not None:
        return replay
    ttl = timedelta(days=body.ttl_days) if body.ttl_days is not None else None
    issued = await _tenancy(request).create_api_key(ctx, body.name, body.role, ttl)
    view = IssuedApiKeyView(key=issued.key, api_key=ApiKeyView.model_validate(issued.api_key))
    return await idem.store(view, 201)


@router.delete("/api-keys/{api_key_id}", response_model=ApiKeyView)
async def revoke_api_key(request: Request, ctx: Ctx, api_key_id: UUID) -> ApiKeyView:
    return ApiKeyView.model_validate(await _tenancy(request).revoke_api_key(ctx, api_key_id))
