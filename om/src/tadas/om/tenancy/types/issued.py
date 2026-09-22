"""Read models that carry a freshly minted secret in the clear, exactly once."""

from datetime import datetime

from tadas.om.base import Platform
from tadas.om.opcontext import OperatorRole, Role
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.user import User


class OrgMembership(Platform):
    org: Org
    user: User
    role: Role


class IssuedLogin(Platform):
    token: str
    expires_at: datetime
    memberships: tuple[OrgMembership, ...]


class IssuedSession(Platform):
    token: str
    expires_at: datetime
    org: Org
    user: User
    role: Role


class IssuedApiKey(Platform):
    key: str
    api_key: ApiKey


class IssuedTicket(Platform):
    """A single-use, short-lived socket ticket; redeeming it re-checks the credential behind it."""

    ticket: str
    expires_at: datetime


class IssuedOperatorToken(Platform):
    """An operator token in the clear, once: one permission, an hour at most."""

    token: str
    expires_at: datetime
    operator_role: OperatorRole


class IssuedTotpSecret(Platform):
    """A freshly minted TOTP secret, once, as the `otpauth://` URI an
    authenticator app reads; only the sealed secret is kept."""

    otpauth_uri: str
