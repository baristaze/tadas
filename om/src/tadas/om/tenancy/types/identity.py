from datetime import datetime
from typing import ClassVar

from tadas.om.base import Identifiable, Trackable
from tadas.om.opcontext import OperatorRole


class Identity(Identifiable, Trackable):
    """A person, across every tenant. Global by nature: a user is this identity inside one org.

    Tadas keeps no password. The identity provider proves the email and hands
    back an issuer and a subject, which this row holds once the person has
    signed in through it; the row, its id, and everything hung on it are
    Tadas's own."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = (
        "issuer",
        "subject",
        "operator_role",
        "totp_secret",
        "totp_confirmed_at",
        "totp_last_step",
    )
    """The link to the provider and the allowlist entry: set by the manager's
    own operations, never copied from a caller."""

    email: str
    # The provider's name for this person: the issuer and the subject under
    # it, unique together. None until the person first signs in through the
    # provider (a person the seeding or the operator plane made, or one an
    # older release made with a password, is linked then, by the verified
    # email).
    issuer: str | None = None
    subject: str | None = None
    # The operator allowlist is this field: a person whose entry is set may be
    # admitted to the operator plane, and the entry says what they may do there.
    operator_role: OperatorRole | None = None
    # The second factor: the TOTP secret sealed under the process's TOTP key,
    # when it was confirmed by a first code, and the last time step a code
    # was accepted for, so a code is never accepted twice. A secret minted and
    # not yet confirmed is not enrolled.
    totp_secret: str | None = None
    totp_confirmed_at: datetime | None = None
    totp_last_step: int | None = None

    @property
    def totp_enrolled(self) -> bool:
        return self.totp_secret is not None and self.totp_confirmed_at is not None
