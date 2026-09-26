"""Read models that carry a freshly minted secret in the clear, exactly once."""

from datetime import datetime

from tadas.om.base import Platform
from tadas.om.opcontext import OperatorRole, Role
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.session import Session
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


class SignInStart(Platform):
    """Where the browser goes to sign in, and the PKCE verifier the caller
    keeps beside its state and hands back with the code. The provider holds
    only the verifier's digest, so a code is worth nothing without it."""

    authorization_url: str
    code_verifier: str


class SignedOut(Platform):
    """A session ended by its own holder, and where the browser goes next to
    end the identity provider's session behind it: None when the sign-in
    left none there (the device sign-in, the local sign-in)."""

    session: Session
    provider_logout_url: str | None = None


class AccountDeleted(Platform):
    """A person's account, gone: when, and where the browser goes next to end
    the identity provider's session behind the session that asked, as a
    sign-out answers. None when the sign-in left no session there."""

    deleted_at: datetime
    provider_logout_url: str | None = None


class OrgDeleted(Platform):
    """A team org its owner deleted: when, and the session the owner lands on
    in their personal org, which replaces the one that asked. None when that
    session could not be made; the owner then signs in again."""

    deleted_at: datetime
    session: IssuedSession | None = None
