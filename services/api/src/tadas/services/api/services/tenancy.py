"""The tenancy service: sign in, choose a tenant, the principal, members,
sessions, and api keys. The two operations before a principal exists take
the stage the gateway reached (the request, then the identity); each
produces the credential the next request presents."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.opcontext import IdentityContext, OpContext, RequestContext
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


class TenancyServiceInterface(ABC):
    @abstractmethod
    async def login(self, rctx: RequestContext, body: LoginRequest) -> IssuedLoginView:
        """Platform-internal: no principal exists yet."""
        ...

    @abstractmethod
    async def exchange_session(
        self, ictx: IdentityContext, body: ExchangeSessionRequest
    ) -> IssuedSessionView:
        """Platform-internal: the identity carries no tenant; the body chooses one."""
        ...

    @abstractmethod
    async def logout(self, ctx: OpContext) -> SessionView: ...

    @abstractmethod
    async def get_me(self, ctx: OpContext) -> MeView: ...

    @abstractmethod
    async def update_me(self, ctx: OpContext, body: UpdateMeRequest) -> UserView: ...

    @abstractmethod
    async def get_identity(self, ctx: OpContext) -> IdentityView: ...

    @abstractmethod
    async def get_org(self, ctx: OpContext) -> OrgView: ...

    @abstractmethod
    async def get_users(self, ctx: OpContext, limit: int) -> list[UserView]: ...

    @abstractmethod
    async def get_memberships(self, ctx: OpContext, limit: int) -> list[MembershipView]: ...

    @abstractmethod
    async def update_membership_role(
        self, ctx: OpContext, user_id: UUID, body: UpdateMembershipRequest
    ) -> MembershipView: ...

    @abstractmethod
    async def remove_member(self, ctx: OpContext, user_id: UUID) -> UserView: ...

    @abstractmethod
    async def get_sessions(self, ctx: OpContext, limit: int) -> list[SessionView]: ...

    @abstractmethod
    async def revoke_session(self, ctx: OpContext, session_id: UUID) -> SessionView: ...

    @abstractmethod
    async def get_api_keys(self, ctx: OpContext, limit: int) -> list[ApiKeyView]: ...

    @abstractmethod
    async def create_api_key(
        self, ctx: OpContext, body: AddApiKeyRequest, api_key_id: UUID
    ) -> IssuedApiKeyView:
        """`api_key_id` is minted by the gateway before the idempotency marker."""
        ...

    @abstractmethod
    async def revoke_api_key(self, ctx: OpContext, api_key_id: UUID) -> ApiKeyView: ...
