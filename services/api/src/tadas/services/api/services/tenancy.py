"""The tenancy service: sign in, choose a tenant, the principal, members,
sessions, and api keys. The two operations without `ctx` run before a
principal exists; each produces the credential the next request presents."""

from uuid import UUID

from tadas.om.opcontext import OpContext
from tadas.services.api.types.tenancy import (
    AddApiKeyRequest,
    ApiKeyView,
    ExchangeSessionRequest,
    IdentityView,
    IssuedApiKeyView,
    IssuedLoginView,
    IssuedSessionView,
    LoginRequest,
    MembershipView,
    MeView,
    OrgView,
    SessionView,
    UpdateMembershipRequest,
    UpdateMeRequest,
    UserView,
)


class TenancyServiceInterface:
    async def login(self, body: LoginRequest) -> IssuedLoginView:
        """Platform-internal: no principal exists yet."""
        ...

    async def exchange_session(
        self, login_credential: str, body: ExchangeSessionRequest
    ) -> IssuedSessionView:
        """Platform-internal: the login credential carries no tenant."""
        ...

    async def logout(self, ctx: OpContext) -> SessionView: ...

    async def get_me(self, ctx: OpContext) -> MeView: ...

    async def update_me(self, ctx: OpContext, body: UpdateMeRequest) -> UserView: ...

    async def get_identity(self, ctx: OpContext) -> IdentityView: ...

    async def get_org(self, ctx: OpContext) -> OrgView: ...

    async def get_users(self, ctx: OpContext, limit: int) -> list[UserView]: ...

    async def get_memberships(self, ctx: OpContext, limit: int) -> list[MembershipView]: ...

    async def update_membership_role(
        self, ctx: OpContext, user_id: UUID, body: UpdateMembershipRequest
    ) -> MembershipView: ...

    async def remove_member(self, ctx: OpContext, user_id: UUID) -> UserView: ...

    async def get_sessions(self, ctx: OpContext, limit: int) -> list[SessionView]: ...

    async def revoke_session(self, ctx: OpContext, session_id: UUID) -> SessionView: ...

    async def get_api_keys(self, ctx: OpContext, limit: int) -> list[ApiKeyView]: ...

    async def create_api_key(self, ctx: OpContext, body: AddApiKeyRequest) -> IssuedApiKeyView: ...

    async def revoke_api_key(self, ctx: OpContext, api_key_id: UUID) -> ApiKeyView: ...
