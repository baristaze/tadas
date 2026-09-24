"""Pure rules of the tenancy namespace: credential parsing, hashing, the
role cap, the TOTP code, who a single sign-on admits, a person's time
zone, and where a list cursor cuts. Values in, values out;
no clock, no storage, no settings. Both storage impls call the cursor rules;
the relational one spells them in SQL and names the rule it mirrors."""

import base64
import hashlib
import hmac
import re
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import quote
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    "opr_": CredentialKind.OPERATOR_TOKEN,
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


def email_digest(email: str) -> str:
    """What a sign-in looks an identity up by, and what the sign-in delay is
    keyed on: the SHA-256 of the address as it was given, in hex. The
    database computes the same digest of the stored address in a generated
    column, so the two never disagree."""
    return hashlib.sha256(email.encode()).hexdigest()


def check_email(email: str) -> None:
    """The shape every stored address has, refused with ValueError: one `@`
    with something before it and a dot after it, no surrounding space, and no
    backslash, which the database's digest reads as an escape. There is no
    verification beyond this, by choice."""
    local, at, domain = email.partition("@")
    if not at or not local or "." not in domain or "@" in domain or email != email.strip():
        raise ValueError("enter an email address")
    if "\\" in email:
        raise ValueError("an email address holds no backslash")


MAX_TIME_ZONE_LENGTH = 64
"""The longest IANA name kept; the longest real one is about thirty."""

_TIME_ZONE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+)*")


def check_time_zone(name: str) -> None:
    """A time zone is an IANA name this process knows ("Europe/Istanbul",
    "UTC"), refused with ValueError otherwise: an offset like "+03:00" moves
    with no daylight saving, and a zone the process cannot read would time a
    reminder by guess."""
    if len(name) > MAX_TIME_ZONE_LENGTH or not _TIME_ZONE_NAME.fullmatch(name):
        raise ValueError("a time zone is an IANA name, like Europe/Istanbul")
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        raise ValueError(f"{name} is not a time zone this server knows") from None


MAX_OPERATOR_TOKEN_TTL = timedelta(hours=1)
"""The longest life an operator token may have. An agent's token expires
within the hour whoever minted it."""

PLATFORM_EMAIL_DOMAIN = "platform.tadas.invalid"
"""The domain of the identities no person signs in as: the provisioner and
the smoke identity. A sign-in with an address in it is refused, so nobody
can take one of them before the grant job makes it. `.invalid` never
resolves, so no mailbox stands behind it either."""


def is_platform_email(email: str) -> bool:
    return email.lower().endswith("@" + PLATFORM_EMAIL_DOMAIN)


TOTP_STEP = timedelta(seconds=30)
TOTP_DIGITS = 6
TOTP_WINDOW = 1
"""RFC 6238 with the defaults every authenticator app assumes: HMAC-SHA1, a
30-second step, six digits. A code is accepted one step either side of
now, for a clock that drifts."""


def totp_step(at: datetime) -> int:
    """The RFC 6238 time step `at` falls in."""
    return int(at.timestamp()) // int(TOTP_STEP.total_seconds())


def totp_code(secret: bytes, step: int) -> str:
    """The code of one time step (RFC 4226's HOTP over the step counter)."""
    mac = hmac.new(secret, step.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = int.from_bytes(mac[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def matching_totp_step(secret: bytes, code: str, at: datetime) -> int | None:
    """The step a presented code belongs to, within the window around `at`,
    or None when it matches none. Every step in the window is compared, in
    constant time, so the answer's timing says nothing about which one
    matched. Whether the step was used already is storage's to say."""
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None
    now = totp_step(at)
    found: int | None = None
    for step in range(now - TOTP_WINDOW, now + TOTP_WINDOW + 1):
        if hmac.compare_digest(totp_code(secret, step), code):
            found = step
    return found


def otpauth_uri(secret: bytes, account: str, issuer: str) -> str:
    """The `otpauth://` URI an authenticator app reads from a QR code or a
    paste: the base32 secret, the account, and the issuer."""
    encoded = base64.b32encode(secret).decode().rstrip("=")
    label = quote(f"{issuer}:{account}")
    return (
        f"otpauth://totp/{label}?secret={encoded}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={int(TOTP_STEP.total_seconds())}"
    )


MAX_SLUG_LENGTH = 48
"""The longest slug an org may have."""

SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
"""A slug: lower-case letters and digits in runs joined by single hyphens."""

SLUG_SUFFIX_LENGTH = 8
"""The random tail of a slug nobody typed: eight of the 36 lower-case letters
and digits, so two orgs of one name part on it and never on a retry."""

PERSONAL_ORG_NAME = "Personal"
"""The name of a personal org whose person gave no name."""


def pkce_challenge(verifier: str) -> str:
    """The S256 challenge of a PKCE verifier (RFC 7636): the SHA-256 of the
    verifier, URL-safe base64 with no padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def email_domain(email: str) -> str:
    """The part of an address after its `@`, in lower case: what an org's
    verified domain is compared with."""
    return email.rpartition("@")[2].lower()


def sso_joins(email: str, verified_domains: tuple[str, ...]) -> bool:
    """Whether a sign-in through an org's single sign-on makes the person a
    member of it: only when their address is in a domain the org has proved
    it owns at the identity provider. The org's own identity provider vouched
    for the person and the org holds the domain, so the org is where they
    belong; anyone else joins by invitation."""
    return email_domain(email) in {domain.lower() for domain in verified_domains}


def check_org(name: str, slug: str | None) -> None:
    """The shape of a new team org, refused with ValueError naming the field:
    a name, and a slug when the person typed one."""
    if not name.strip():
        raise ValueError("an organization name is required")
    if slug is not None and (len(slug) > MAX_SLUG_LENGTH or not SLUG_PATTERN.fullmatch(slug)):
        raise ValueError(
            f"a slug is lower-case letters and digits joined by hyphens, "
            f"at most {MAX_SLUG_LENGTH} characters"
        )


def personal_org_name(display_name: str) -> str:
    """A personal org is named after its person, or "Personal" when the
    person gave no name."""
    return display_name.strip() or PERSONAL_ORG_NAME


def slug_from_name(name: str, suffix: str) -> str:
    """The slug an org gets when nobody typed one: the name in lower-case
    ASCII letters and digits, every other run one hyphen, cut to leave room,
    then the random `suffix`. A name with nothing to keep gives "org". The
    portal suggests the same stem for a name the person types."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    stem = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    stem = stem[: MAX_SLUG_LENGTH - len(suffix) - 1].rstrip("-") or "org"
    return f"{stem}-{suffix}"


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


def sign_in_delay(
    failures: int,
    last_failed_at: datetime | None,
    now: datetime,
    *,
    free: int,
    base: timedelta,
    cap: timedelta,
) -> timedelta:
    """How long the next sign-in of an email waits before it is checked:
    nothing for the first `free` failures of a run, then `base`, doubling
    with each failure after, never more than `cap`, counted from the last
    failure. Zero once that has passed."""
    if failures < free or last_failed_at is None:
        return timedelta(0)
    wait = min(base * (2 ** (failures - free)), cap)
    return max(last_failed_at + wait - now, timedelta(0))
