from datetime import datetime
from uuid import UUID

from pydantic import Field

from tadas.om.opcontext import CredentialKind, OperatorRole, Permission, Role
from tadas.om.tenancy.rules import MAX_API_KEY_TTL
from tadas.services.api.types.common import RequestBody, View


class OrgView(View):
    id: UUID
    name: str
    slug: str
    created_at: datetime
    deleted_at: datetime | None = None


class UserView(View):
    id: UUID
    email: str
    display_name: str
    created_at: datetime


class IdentityView(View):
    """The person behind the caller's user; never carries the password hash.
    `operator_role` is the allowlist entry: null for a person who is not an
    operator."""

    id: UUID
    email: str
    operator_role: OperatorRole | None
    created_at: datetime


class UpdateMeRequest(RequestBody):
    display_name: str = Field(min_length=1, max_length=200)


class MembershipView(View):
    id: UUID
    user_id: UUID
    role: Role
    teams: tuple[UUID, ...]


class UpdateMembershipRequest(RequestBody):
    role: Role


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


class SessionView(View):
    """Only the hash of a token is ever kept, so a session view carries no secret."""

    id: UUID
    credential_kind: CredentialKind
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class ApiKeyView(View):
    id: UUID
    name: str
    role: Role
    user_id: UUID
    created_at: datetime
    expires_at: datetime
    deleted_at: datetime | None


class UserPageView(View):
    """One page of the tenant's members. `next_cursor` fetches the next page
    and is null on the last one, so a client reads every member instead of
    whatever a fixed limit happened to cover."""

    items: list[UserView]
    next_cursor: str | None


class ApiKeyPageView(View):
    """One page of the api key list, newest first; `next_cursor` as on
    `UserPageView`."""

    items: list[ApiKeyView]
    next_cursor: str | None


class AddApiKeyRequest(RequestBody):
    name: str
    role: Role
    ttl_days: int | None = Field(default=None, ge=1, le=MAX_API_KEY_TTL.days)


class IssuedApiKeyView(View):
    """The key in the clear is present on the first response only: the stored
    outcome of the create carries no secret, so a replay under the same
    Idempotency-Key answers with `key` null and `Idempotent-Replayed: true`. A
    client that lost the first response revokes the key and issues another."""

    secret_fields = frozenset({"key"})

    key: str | None
    api_key: ApiKeyView
