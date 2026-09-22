"""Pure rules of the tenancy namespace: credential parsing, hashing, the
role cap, and where a list cursor cuts. Values in, values out; no clock, no
storage, no settings. Both storage impls call the cursor rules; the
relational one spells them in SQL and names the rule it mirrors."""

import hashlib
import hmac
import re
from datetime import timedelta
from uuid import UUID

from tadas.om.opcontext import CredentialKind, Role
from tadas.om.tenancy.types.role import ROLE_RANK

MAX_API_KEY_TTL = timedelta(days=90)
"""The longest life a tenant may ask of an api key. `TenancyOptions.api_key_ttl`
defaults to it and the wire type bounds its request field by it."""

CREDENTIAL_PREFIXES: dict[str, CredentialKind] = {
    "ses_": CredentialKind.SESSION_TOKEN,
    "key_": CredentialKind.API_KEY,
    "lgn_": CredentialKind.LOGIN,
    "tkt_": CredentialKind.SOCKET_TICKET,
}

PREFIX_FOR_KIND: dict[CredentialKind, str] = {
    kind: prefix for prefix, kind in CREDENTIAL_PREFIXES.items()
}


def credential_kind_of(credential: str) -> CredentialKind | None:
    """The kind a credential's prefix announces, or None for an unknown prefix."""
    for prefix, kind in CREDENTIAL_PREFIXES.items():
        if credential.startswith(prefix):
            return kind
    return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


DUMMY_PASSWORD_HASH = (
    "scrypt$000102030405060708090a0b0c0d0e0f$"
    "6e4b2a03fcd2540436bfc7373ac964ddf9c36b407915201ad5a06f53bf74600c"
    "fe8d883942761592340c6a42909826638155e1d2c649d6b4d773967e17439de9"
)
"""A stored hash to verify against when the email is unknown, so a miss
costs the same scrypt as a wrong password and the response time does not
say which emails exist. The outcome of that verification is discarded; a
sign-in with an unknown email is refused whatever it says."""


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, _digest = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(candidate, stored)


MIN_PASSWORD_LENGTH = 8
"""The shortest password a sign-up accepts. A sign-in checks no length: a
password set before this rule, or by the seeding, still signs in."""

MAX_SLUG_LENGTH = 48
"""The longest slug a sign-up accepts."""

SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
"""A sign-up's slug: lower-case letters and digits in runs joined by single hyphens."""


def check_sign_up(email: str, password: str, display_name: str, org_name: str, slug: str) -> None:
    """The shape of a sign-up, refused with ValueError naming the field. There
    is no email verification: an address with one `@` and a dot after it is
    the whole check, a choice and not an oversight (the sign-up is the door a
    deployed environment has, and a demo needs no mailbox). It has two costs,
    both accepted: a held address answers as a conflict, so anyone can tell
    which addresses have an account, and anyone can sign up with an address
    that is not theirs. And with no verified address there is no account
    recovery: a forgotten password is an account an operator re-creates."""
    local, at, domain = email.partition("@")
    if not at or not local or "." not in domain or "@" in domain or email != email.strip():
        raise ValueError("enter an email address")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"a password has at least {MIN_PASSWORD_LENGTH} characters")
    if not display_name.strip():
        raise ValueError("a display name is required")
    if not org_name.strip():
        raise ValueError("an organization name is required")
    if len(slug) > MAX_SLUG_LENGTH or not SLUG_PATTERN.fullmatch(slug):
        raise ValueError(
            f"a slug is lower-case letters and digits joined by hyphens, "
            f"at most {MAX_SLUG_LENGTH} characters"
        )


def role_at_most(requested: Role, ceiling: Role) -> bool:
    """A credential never carries a role above its issuer's. The ladder holds
    the person roles only: the service role is at most no person role and no
    person role is at most it, so the answer is False whenever either side is
    `Role.SERVICE`, and the operation that issues a credential refuses that
    role by name before it asks."""
    if requested is Role.SERVICE or ceiling is Role.SERVICE:
        return False
    return ROLE_RANK[requested] <= ROLE_RANK[ceiling]


def capped_role(requested: Role, ceiling: Role) -> Role:
    """The requested role when it is at most the ceiling, else the ceiling. A
    service role asked for is capped like any role above the ceiling; a
    service role as the ceiling is refused, because a membership never
    carries it and nothing is capped at a role that is not a rung."""
    if ceiling is Role.SERVICE:
        raise ValueError("the service role is not a rung of the ladder; nothing is capped at it")
    return requested if role_at_most(requested, ceiling) else ceiling


def is_after_in_id_order(entity_id: UUID, cursor: UUID) -> bool:
    """A list read by id ascending - the tenant's users - puts a row on the
    next page when its id sorts strictly after the cursor's."""
    return entity_id > cursor


def is_after_newest_first(entity_id: UUID, cursor: UUID) -> bool:
    """A list read newest first - sessions, api keys - is by id descending,
    since an id is minted in time order; a row is on the next page when its
    id sorts strictly before the cursor's."""
    return entity_id < cursor
