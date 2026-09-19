from datetime import timedelta
from uuid import UUID

from tadas.om.opcontext import IdentityContext, OpContext, RequestContext
from tadas.om.tenancy import TenancyManagerInterface
from tadas.services.api.services.tenancy import TenancyServiceInterface
from tadas.services.api.types.common import clamp_limit
from tadas.services.api.types.tenancy import (
    AddApiKeyRequest,
    ApiKeyView,
    ExchangeSessionRequest,
    IdentityView,
    IssuedApiKeyView,
    IssuedLoginView,
    IssuedSessionView,
    LoginRequest,
    MembershipChoiceView,
    MembershipView,
    MeView,
    OrgView,
    SessionView,
    UpdateMembershipRequest,
    UpdateMeRequest,
    UserView,
)


class TenancyServiceImpl(TenancyServiceInterface):
    def __init__(self, tenancy: TenancyManagerInterface) -> None:
        self._tenancy = tenancy

    async def login(self, rctx: RequestContext, body: LoginRequest) -> IssuedLoginView:
        issued = await self._tenancy.login(rctx, body.email, body.password)
        return IssuedLoginView(
            token=issued.token,
            expires_at=issued.expires_at,
            memberships=[MembershipChoiceView.model_validate(m) for m in issued.memberships],
        )

    async def exchange_session(
        self, ictx: IdentityContext, body: ExchangeSessionRequest
    ) -> IssuedSessionView:
        issued = await self._tenancy.exchange_login(ictx, body.org_id)
        return IssuedSessionView.model_validate(issued)

    async def logout(self, ctx: OpContext) -> SessionView:
        return SessionView.model_validate(await self._tenancy.logout(ctx))

    async def get_me(self, ctx: OpContext) -> MeView:
        # The context carries ids; the entities are loaded by the manager.
        user = await self._tenancy.get_user(ctx, ctx.user_id)
        org = await self._tenancy.get_org(ctx)
        return MeView(
            user=UserView.model_validate(user),
            org=OrgView.model_validate(org),
            role=ctx.security.role,
            permissions=ctx.security.permissions,
            app=ctx.app.type.value,
        )

    async def update_me(self, ctx: OpContext, body: UpdateMeRequest) -> UserView:
        me = await self._tenancy.get_user(ctx, ctx.user_id)
        user = me.model_copy(update={"display_name": body.display_name})
        return UserView.model_validate(await self._tenancy.update_user(ctx, user))

    async def get_identity(self, ctx: OpContext) -> IdentityView:
        return IdentityView.model_validate(await self._tenancy.get_identity(ctx))

    async def get_org(self, ctx: OpContext) -> OrgView:
        return OrgView.model_validate(await self._tenancy.get_org(ctx))

    async def get_users(self, ctx: OpContext, limit: int) -> list[UserView]:
        users = await self._tenancy.get_users(ctx, clamp_limit(limit))
        return [UserView.model_validate(u) for u in users]

    async def get_memberships(self, ctx: OpContext, limit: int) -> list[MembershipView]:
        memberships = await self._tenancy.get_memberships(ctx, clamp_limit(limit))
        return [MembershipView.model_validate(m) for m in memberships]

    async def update_membership_role(
        self, ctx: OpContext, user_id: UUID, body: UpdateMembershipRequest
    ) -> MembershipView:
        updated = await self._tenancy.update_membership_role(ctx, user_id, body.role)
        return MembershipView.model_validate(updated)

    async def remove_member(self, ctx: OpContext, user_id: UUID) -> UserView:
        return UserView.model_validate(await self._tenancy.remove_member(ctx, user_id))

    async def get_sessions(self, ctx: OpContext, limit: int) -> list[SessionView]:
        sessions = await self._tenancy.get_sessions(ctx, clamp_limit(limit))
        return [SessionView.model_validate(s) for s in sessions]

    async def revoke_session(self, ctx: OpContext, session_id: UUID) -> SessionView:
        return SessionView.model_validate(await self._tenancy.revoke_session(ctx, session_id))

    async def get_api_keys(self, ctx: OpContext, limit: int) -> list[ApiKeyView]:
        keys = await self._tenancy.get_api_keys(ctx, clamp_limit(limit))
        return [ApiKeyView.model_validate(k) for k in keys]

    async def create_api_key(
        self, ctx: OpContext, body: AddApiKeyRequest, api_key_id: UUID
    ) -> IssuedApiKeyView:
        ttl = timedelta(days=body.ttl_days) if body.ttl_days is not None else None
        issued = await self._tenancy.create_api_key(ctx, body.name, body.role, ttl, api_key_id)
        return IssuedApiKeyView(key=issued.key, api_key=ApiKeyView.model_validate(issued.api_key))

    async def revoke_api_key(self, ctx: OpContext, api_key_id: UUID) -> ApiKeyView:
        return ApiKeyView.model_validate(await self._tenancy.revoke_api_key(ctx, api_key_id))
