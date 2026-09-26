from datetime import datetime

from sqlalchemy import BigInteger, Column, Computed, DateTime, Index, Integer, Text, text
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
        # One identity per subject of an issuer: the provider's sign-in lookup.
        Index(
            "uq_identities_issuer_subject",
            "issuer",
            "subject",
            unique=True,
            postgresql_where=text("subject IS NOT NULL"),
        ),
        # Three dead columns, in the table and out of the mapping. Tadas keeps
        # no password (sign-in is the identity provider's), and the run of
        # failed sign-ins is `sign_in_delays`, keyed on the email's digest.
        # A mapped column is named by every insert the mapper emits, deferred
        # or not, so the release before this one names all three in each new
        # identity, and a migration runs before the services roll: a drop here
        # would fail its sign-ups mid-rollout. Out of the mapping, no statement
        # of this release names them, and the release after this one drops
        # them with these lines. The hashes are already gone (migration
        # 202609280000).
        Column("password_hash", Text(), nullable=True),
        Column("failed_sign_ins", Integer(), server_default=text("0"), nullable=False),
        Column("last_failed_sign_in_at", DateTime(timezone=True), nullable=True),
    )
    __mapper_args__ = {
        "exclude_properties": ["password_hash", "failed_sign_ins", "last_failed_sign_in_at"]
    }
    email: Mapped[str]
    email_digest: Mapped[str] = mapped_column(Computed(EMAIL_DIGEST, persisted=True))
    issuer: Mapped[str | None]
    subject: Mapped[str | None]
    operator_role: Mapped[str | None]
    totp_secret: Mapped[str | None]
    totp_confirmed_at: Mapped[datetime | None]
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger())
    time_zone: Mapped[str | None]
