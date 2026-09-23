"""Slack: the one interface the platform posts through, and the errors a
caller decides on. The real client speaks the Web API with the bot token; the
twin answers in-process and records what it was asked. A caller never knows
which it holds.

The errors are the decision a caller needs, not Slack's whole vocabulary: a
rate limit says when to come back, an unusable channel says the connection is
broken until a person fixes it, and anything else is a failure worth a retry."""

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from tadas.infra.exceptions import InfraException

UNUSABLE_CHANNEL_ERRORS = frozenset({"channel_not_found", "not_in_channel", "is_archived"})
"""Slack's answers that no retry changes: the channel is gone, archived, or
the app was never invited. A person fixes each; the platform stops posting."""


class SlackError(InfraException):
    """Root of what a Slack call raises: a provider is a dependency like a
    backend, so its refusals are infra's. `slack_code` is Slack's own error
    string, or the transport's reason when Slack never answered."""

    http_status = 502
    code = "slack_failed"

    def __init__(self, slack_code: str, message: str | None = None) -> None:
        super().__init__(message or slack_code)
        self.slack_code = slack_code


class SlackRateLimited(SlackError):
    """Slack asked the caller to wait (HTTP 429); `retry_after` is how long."""

    def __init__(self, retry_after: timedelta) -> None:
        super().__init__("ratelimited", f"rate limited; retry after {retry_after}")
        self.retry_after = retry_after


class SlackChannelUnusable(SlackError):
    """The channel refuses posts until a person fixes it: one of
    `UNUSABLE_CHANNEL_ERRORS`."""


class SlackNotConfigured(SlackError):
    """This process holds no bot token, so nothing can be posted."""

    def __init__(self) -> None:
        super().__init__("not_configured", "no Slack bot token is configured")


class SlackFailed(SlackError):
    """Any other refusal or transport failure; a retry may change it."""


class SlackInterface(ABC):
    @abstractmethod
    async def post_message(self, channel_id: str, text: str) -> str:
        """Posts `text` to the channel as the app (`chat.postMessage`); returns
        the message's timestamp, which names it in the channel."""
        ...

    @abstractmethod
    async def reply_in_thread(self, channel_id: str, thread_ts: str, text: str) -> str:
        """Posts `text` in the thread of the message `thread_ts`."""
        ...

    @abstractmethod
    async def respond(self, response_url: str, text: str) -> None:
        """Answers a slash command through the `response_url` Slack sent with
        it, visible to the person who typed it alone. The URL must be one of
        Slack's own; any other is refused before a request is made."""
        ...

    @abstractmethod
    async def publish_home(self, user_id: str, view: dict[str, Any]) -> None:
        """Publishes the App Home view for one person (`views.publish`)."""
        ...

    @abstractmethod
    def describe(self) -> str: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


def error_for(code: str, retry_after: timedelta | None = None) -> SlackError:
    """The error a caller decides on, from Slack's own answer."""
    if retry_after is not None or code == "ratelimited":
        return SlackRateLimited(retry_after or timedelta(seconds=30))
    if code in UNUSABLE_CHANNEL_ERRORS:
        return SlackChannelUnusable(code)
    return SlackFailed(code)


RESPONSE_URL_PREFIX = "https://hooks.slack.com/"
"""Where Slack's `response_url` points. A command's answer goes nowhere else."""


def is_response_url(url: str) -> bool:
    return url.startswith(RESPONSE_URL_PREFIX)
