"""The channel an org connected, and the codes that connect one."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from tadas.om.base import Created, Identifiable, Platform, SoftDeletable, Trackable


class SlackConnectionStatus(StrEnum):
    OK = "ok"
    BROKEN = "broken"  # Slack refused a post for good: the channel is gone, archived, or left


class SlackConnection(Identifiable, Trackable, SoftDeletable):
    """One Slack channel, bound to one org. An org has at most one living
    connection and a channel belongs to at most one org. `created_by` is the
    member who issued the code the channel was linked with, and what `/tadas
    add` creates is attributed to them. Relinking writes over the same row;
    disconnecting deletes it."""

    team_id: str
    channel_id: str
    linked_by_slack_user: str  # the Slack user who typed the code, for the record
    status: SlackConnectionStatus = SlackConnectionStatus.OK
    broken_reason: str | None = None  # the error Slack answered with, when broken


class SlackLinkCode(Identifiable, Created):
    """A one-time code that links a channel to the org. Only its digest is
    kept; it expires in minutes and redeeming it is one conditional write, so
    a code works once."""

    user_id: UUID  # the member who asked for it, and who the connection names
    code_hash: str
    expires_at: datetime
    redeemed_at: datetime | None = None


class IssuedSlackLinkCode(Platform):
    """The code in the clear, shown once, beside when it stops working."""

    code: str
    expires_at: datetime


class SlackPost(Identifiable, Created):
    """A message the platform posted, keyed by the work that posted it: a
    retried post finds its key here and posts nothing. Slack's timestamp
    names the message in the channel."""

    key: UUID  # the posting work item's idempotency key
    channel_id: str
    ts: str
