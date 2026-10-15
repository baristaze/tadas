"""The payload of the slack namespace's kind of work (`slack.kinds`)."""

from enum import StrEnum

from tadas.om.base import OmBase


class SlackPostEvent(StrEnum):
    CREATED = "created"
    COMPLETED = "completed"
    REMINDED = "reminded"


class SlackPostPayload(OmBase):
    """What happened to the task the item targets. The message is composed
    when the item runs, from the task as it is then; the payload carries no
    field of it."""

    event: SlackPostEvent
