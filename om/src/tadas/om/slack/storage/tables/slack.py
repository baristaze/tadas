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


class SlackInstallations(IdentifiableMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "slack_installations"
    # One living installation per org, and one org per living workspace:
    # unique among the living, so an uninstalled org or workspace installs
    # again. The sweep's read of the dead ones has no index: an org has a
    # handful of installations over its life, not a list.
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_slack_installations_org_id",
            "org_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_slack_installations_team_id",
            "team_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
    team_id: Mapped[str]
    team_name: Mapped[str]
    app_id: Mapped[str]
    bot_user_id: Mapped[str]
    scopes: Mapped[str]
    installed_by_slack_user: Mapped[str]
    credential_ref: Mapped[str]
    token_expires_at: Mapped[datetime | None]
    refreshing_until: Mapped[datetime | None]
    channel_id: Mapped[str | None]
    status: Mapped[str]
    broken_reason: Mapped[str | None]


class SlackInstallStates(IdentifiableMixin, CreatedMixin, Base):
    __tablename__ = "slack_install_states"
    __table_args__ = (Index("uq_slack_install_states_state_hash", "state_hash", unique=True),)
    user_id: Mapped[UUID]
    state_hash: Mapped[str]
    expires_at: Mapped[datetime]
    redeemed_at: Mapped[datetime | None]


class SlackPosts(IdentifiableMixin, CreatedMixin, Base):
    __tablename__ = "slack_posts"
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_slack_posts_org_id_key", "org_id", "key", unique=True),
        # What the purge reads: the tenant's posts by birth.
        Index("ix_slack_posts_org_id_created_at", "org_id", "created_at"),
    )
    key: Mapped[UUID]
    channel_id: Mapped[str]
    ts: Mapped[str]
