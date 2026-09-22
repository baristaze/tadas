from datetime import datetime

from sqlalchemy import BigInteger, Computed, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from tadas.om.storage.tables.base import Base, GlobalIdentifiableMixin, TrackableMixin

EMAIL_DIGEST = "encode(sha256(decode(email, 'escape')), 'hex')"
"""The digest a sign-in looks an identity up by (`rules.email_digest`),
computed by the database from the stored address, so every writer, an older
release included, leaves a row the lookup finds. A generated column takes
only immutable functions, and `decode(..., 'escape')` is the immutable one
that yields the address's UTF-8 bytes; it reads a backslash as an escape,
which is why an address holds none (`rules.check_email`)."""


class Identities(GlobalIdentifiableMixin, TrackableMixin, Base):
    __tablename__ = "identities"
    __table_args__ = (
        Index("uq_identities_email", "email", unique=True),
        Index("uq_identities_email_digest", "email_digest", unique=True),
    )
    email: Mapped[str]
    email_digest: Mapped[str] = mapped_column(Computed(EMAIL_DIGEST, persisted=True))
    password_hash: Mapped[str]
    operator_role: Mapped[str | None]
    totp_secret: Mapped[str | None]
    totp_confirmed_at: Mapped[datetime | None]
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger())
    # The run of failed sign-ins moved to `sign_in_delays`, keyed on the
    # email's digest. The columns are dead and deferred: no read names them
    # and no write sets them, the database's default fills the one that is
    # NOT NULL, and the mapping stays so the schema check has something to
    # compare with. The release before this one still named them in every
    # identity read, and a migration runs before the services roll, so a drop
    # here would break a sign-in it served mid-rollout. The release after
    # this one drops the columns and these two lines.
    failed_sign_ins: Mapped[int] = mapped_column(server_default=text("0"), deferred=True)
    last_failed_sign_in_at: Mapped[datetime | None] = mapped_column(deferred=True)
