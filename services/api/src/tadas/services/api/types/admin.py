"""Wire types of the operator plane. The views a tenant's rows are read into
are the tenant's own (`OrgView`, `UserPageView`, `TaskPageView`,
`EventView`): an operator sees what the tenant sees, under the tenant named
in the path."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from tadas.om.opcontext import OperatorRole, Role
from tadas.om.tenancy.rules import MAX_OPERATOR_TOKEN_TTL
from tadas.services.api.types.common import RequestBody, View


class CreateOrgRequest(RequestBody):
    """An org with its owner, as `bootstrap` seeds one. The owner's identity
    is created with the password, or kept with its own when the email is
    known already."""

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100)
    owner_email: str = Field(min_length=1)
    owner_password: str = Field(min_length=1)
    owner_name: str = Field(min_length=1, max_length=200)


class AddMemberRequest(RequestBody):
    """A person in the org, as `add-member` seeds one; the owner and the
    service role are refused, since the one owner is the one the create
    minted."""

    email: str = Field(min_length=1)
    password: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=200)
    role: Role


class OperatorView(View):
    """Who the operator plane admitted: the identity and what its allowlist
    entry grants, so a skill checks it holds the entry it expects before it
    reads anything."""

    identity_id: UUID
    email: str
    operator_role: OperatorRole


class PlatformSizeView(View):
    """How big the platform is, what the first responder to an alarm reads
    before it escalates: live tenants and users, and the tasks created and
    events produced in the last twenty-four hours, a window that starts at
    `since` and ends at the read."""

    tenants: int
    users: int
    tasks_last_24h: int
    events_last_24h: int
    since: datetime


class IssuedTotpSecretView(View):
    """A freshly minted TOTP secret, once, as the `otpauth://` URI an
    authenticator app reads. A replay carries none."""

    secret_fields = frozenset({"otpauth_uri"})

    otpauth_uri: str | None


class ConfirmTotpRequest(RequestBody):
    """The first code from the authenticator, which confirms the secret."""

    totp_code: str = Field(min_length=6, max_length=6)


class TotpConfirmedView(View):
    """The second factor is enrolled: from now on the operator plane admits
    this identity only on a sign-in that verified a code, so the next
    request signs in again with one."""

    identity_id: UUID
    confirmed_at: datetime


class MintOperatorTokenRequest(RequestBody):
    """One permission, never wider than the caller's entry (`write` implies
    `read`), and a lifetime of at most an hour, an hour when absent."""

    permission: OperatorRole
    expires_in: int | None = Field(
        default=None, ge=1, le=int(MAX_OPERATOR_TOKEN_TTL.total_seconds())
    )


class IssuedOperatorTokenView(View):
    """The token in the clear on the first response only; a replay under the
    same Idempotency-Key answers with `token` null. A client that lost the
    first answer mints another; the lost one expires within the hour."""

    secret_fields = frozenset({"token"})

    token: str | None
    expires_at: datetime
    permission: OperatorRole


class ResetPasswordRequest(RequestBody):
    """The person, by email, and the password they sign in with from now on."""

    email: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=200)


class PasswordResetView(View):
    """Whose password was reset; the reset is audited with the operator."""

    identity_id: UUID
    email: str
