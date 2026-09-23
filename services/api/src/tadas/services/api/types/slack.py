from datetime import datetime
from uuid import UUID

from tadas.om.slack.types.connection import SlackConnectionStatus
from tadas.services.api.types.common import View


class SlackConnectionView(View):
    """The Slack channel the org is connected to. `status` is `broken` when
    Slack refused a post for good (`broken_reason` says which refusal); the
    channel is linked again to mend it. `created_by` is the member whose code
    linked it, whom a task added from the channel is attributed to."""

    id: UUID
    team_id: str
    channel_id: str
    status: SlackConnectionStatus
    broken_reason: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class SlackStatusView(View):
    """Whether the org has a channel connected, and which."""

    connection: SlackConnectionView | None


class IssuedSlackLinkCodeView(View):
    """A one-time code, typed into a Slack channel as `/tadas link <code>`. It
    works once, until `expires_at`, and is shown here only: the platform keeps
    its digest."""

    secret_fields = frozenset({"code"})

    code: str | None
    expires_at: datetime
