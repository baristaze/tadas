from datetime import datetime
from uuid import UUID

from tadas.om.opcontext import Permission, Role
from tadas.services.api.types.common import RequestBody, View


class OrgView(View):
    id: UUID
    name: str
    slug: str
    created_at: datetime


class UserView(View):
    id: UUID
    email: str
    display_name: str
    created_at: datetime


class MembershipView(View):
    id: UUID
    user_id: UUID
    role: Role
    teams: tuple[UUID, ...]


class MembershipChoiceView(View):
    org: OrgView
    user: UserView
    role: Role


class LoginRequest(RequestBody):
    email: str
    password: str


class IssuedLoginView(View):
    """Carries the freshly minted login credential in the clear, once."""

    token: str
    expires_at: datetime
    memberships: list[MembershipChoiceView]


class ExchangeSessionRequest(RequestBody):
    org_id: UUID


class IssuedSessionView(View):
    token: str
    expires_at: datetime
    org: OrgView
    user: UserView
    role: Role


class MeView(View):
    user: UserView
    org: OrgView
    role: Role
    permissions: tuple[Permission, ...]
    app: str


class ApiKeyView(View):
    id: UUID
    name: str
    role: Role
    user_id: UUID
    created_at: datetime
    expires_at: datetime
    deleted_at: datetime | None


class AddApiKeyRequest(RequestBody):
    name: str
    role: Role
    ttl_days: int | None = None


class IssuedApiKeyView(View):
    key: str
    api_key: ApiKeyView
