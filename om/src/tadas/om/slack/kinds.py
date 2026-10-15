"""The slack namespace's kinds of work, which the business root registers in
`KINDS` below its marker (`work.kinds`)."""

from enum import StrEnum

from tadas.om.context import Permission
from tadas.om.slack.types.work import SlackPostPayload
from tadas.om.work.kinds import WorkKindSpec


class SlackKind(StrEnum):
    """The names of the slack namespace's kinds of work."""

    SLACK_POST = "SLACK_POST"  # a message to the Slack channel the org bound


SLACK_KINDS: tuple[WorkKindSpec, ...] = (
    WorkKindSpec(SlackKind.SLACK_POST, SlackPostPayload, Permission.WRITE),
)
"""The slack namespace's kinds, each on the default lane."""
