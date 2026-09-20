"""Pure rules of the tenancy namespace: credential parsing, hashing, and the
role cap. Values in, values out; no clock, no storage, no settings."""

import hashlib
import hmac
from datetime import timedelta

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
