from datetime import datetime
from uuid import UUID

from pydantic import Field

from tadas.om.opcontext import CredentialKind, OperatorRole, Permission, Role
from tadas.om.tenancy.rules import MAX_API_KEY_TTL
from tadas.om.tenancy.types.org import OrgKind
from tadas.services.api.types.common import RequestBody, View


class OrgView(View):
    """`kind` says what the org is for: every person has one `personal` org,
    made with them, which is never deleted and never changes hands; every
    other org is a `team` org."""

    id: UUID
    name: str
    slug: str
    kind: OrgKind
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
    """An email and a password, and the code from an authenticator when the
    identity has a second factor enrolled. A tenant's sign-in needs none; the
    operator plane admits an enrolled operator only on a sign-in that
    verified one. A code used once is refused."""

    email: str
    password: str
    totp_code: str | None = Field(default=None, min_length=6, max_length=6)


class SignUpRequest(RequestBody):
    """A new person and their password. The person's personal org is made
    with them, named and slugged for them, so a sign-up names no org. The
    answer is a sign-in's (`IssuedLoginView`), so the client goes on through
    the same choice and exchange; a held email is 409. No email is verified.
    `org_name` and `org_slug` are what a sign-up named before and are
    ignored; the release after this one refuses them."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    org_name: str | None = Field(default=None, max_length=200, deprecated=True)
    org_slug: str | None = Field(default=None, max_length=48, deprecated=True)


class CreateTeamOrgRequest(RequestBody):
    """A team org the caller makes and owns. `slug` is lower-case letters and
    digits joined by hyphens; left out, one is made from the name. A taken
    slug is 409."""

    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=48)


class IssuedLoginView(View):
    """Carries the freshly minted login credential in the clear, once."""

    token: str
    expires_at: datetime
    memberships: list[MembershipChoiceView]


class MembershipChoicePageView(View):
    """One page of the signed-in person's places, each the org, the user, and
    the role: the same choice a sign-in answers with. `next_cursor` as on
    `UserPageView`."""

    items: list[MembershipChoiceView]
    next_cursor: str | None


class ExchangeSessionRequest(RequestBody):
    """The org to enter. Presented with the sign-in credential, it opens the
    first session; presented with a session, it is a switch, and that session
    ends in the same write."""

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


class MembershipPageView(View):
    """One page of the tenant's memberships, by user id; `next_cursor` as on
    `UserPageView`. A page read with the same limit as a page of users
    covers the same members, so roles pair with members page for page."""

    items: list[MembershipView]
    next_cursor: str | None


class OrgPageView(View):
    """One page of every org, by id, for the operator plane; `next_cursor` as
    on `UserPageView`."""

    items: list[OrgView]
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
