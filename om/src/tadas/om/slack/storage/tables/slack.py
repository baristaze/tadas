from datetime import datetime
from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped

from tadas.om.storage.tables.base import (
    Base,
    CreatedMixin,
    IdentifiableMixin,
    SoftDeletableMixin,
    TrackableMixin,
)


class SlackConnections(IdentifiableMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "slack_connections"
    # One living connection per org, and one org per living channel: unique
    # among the living, so a disconnected org or channel can link again. The
    # sweep's read of the dead ones has no index: an org has a handful of
    # connections over its life, not a list.
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_slack_connections_org_id",
            "org_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_slack_connections_team_id_channel_id",
            "team_id",
            "channel_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
    team_id: Mapped[str]
    channel_id: Mapped[str]
    linked_by_slack_user: Mapped[str]
    status: Mapped[str]
    broken_reason: Mapped[str | None]


class SlackLinkCodes(IdentifiableMixin, CreatedMixin, Base):
    __tablename__ = "slack_link_codes"
    __table_args__ = (Index("uq_slack_link_codes_code_hash", "code_hash", unique=True),)
    user_id: Mapped[UUID]
    code_hash: Mapped[str]
    expires_at: Mapped[datetime]
    redeemed_at: Mapped[datetime | None]


class SlackPosts(IdentifiableMixin, CreatedMixin, Base):
    __tablename__ = "slack_posts"
    __org_id_index__ = False
    __table_args__ = (Index("uq_slack_posts_org_id_key", "org_id", "key", unique=True),)
    key: Mapped[UUID]
    channel_id: Mapped[str]
    ts: Mapped[str]
