"""Pure rules of the tenancy namespace: credential parsing, hashing, and the
role cap. Values in, values out; no clock, no storage, no settings."""

import hashlib
import hmac

from tadas.om.tenancy.types.role import ROLE_RANK, CredentialKind, Role

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
    """A credential never carries a role above its issuer's."""
    return ROLE_RANK[requested] <= ROLE_RANK[ceiling]


def capped_role(requested: Role, ceiling: Role) -> Role:
    return requested if role_at_most(requested, ceiling) else ceiling
