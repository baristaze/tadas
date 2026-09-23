"""The deterministic twin: answers in-process, records every call, and fails
on request, so a test can drive the rate limit and the unusable channel the
real service would. It refuses to run outside a local environment, and every
message it posts carries a timestamp that says it came from the twin."""

import logging
from dataclasses import dataclass, field
from typing import Any

from tadas.integrations.slack import SlackError, SlackFailed, SlackInterface, is_response_url

log = logging.getLogger(__name__)

TWIN_ENVIRONMENTS = frozenset({"local", "test"})


@dataclass(frozen=True)
class TwinPost:
    channel_id: str
    text: str
    ts: str
    thread_ts: str | None = None


@dataclass
class SlackTwinImpl(SlackInterface):
    environment: str
    posts: list[TwinPost] = field(default_factory=list)
    responses: list[tuple[str, str]] = field(default_factory=list)
    homes: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    failures: list[SlackError] = field(default_factory=list)
    """Errors the next calls raise, first in first out: a test's way of making
    Slack refuse."""

    def __post_init__(self) -> None:
        if self.environment not in TWIN_ENVIRONMENTS:
            raise ValueError(f"the Slack twin runs locally only, not in {self.environment!r}")

    def fail_next(self, error: SlackError) -> None:
        self.failures.append(error)

    async def post_message(self, channel_id: str, text: str) -> str:
        self._maybe_fail()
        ts = f"twin.{len(self.posts) + 1:06d}"
        self.posts.append(TwinPost(channel_id, text, ts))
        log.info("slack twin posted %s to %s: %s", ts, channel_id, text)
        return ts

    async def reply_in_thread(self, channel_id: str, thread_ts: str, text: str) -> str:
        self._maybe_fail()
        ts = f"twin.{len(self.posts) + 1:06d}"
        self.posts.append(TwinPost(channel_id, text, ts, thread_ts))
        return ts

    async def respond(self, response_url: str, text: str) -> None:
        if not is_response_url(response_url):
            raise SlackFailed("invalid_response_url", "a response_url that is not Slack's")
        self._maybe_fail()
        self.responses.append((response_url, text))

    async def publish_home(self, user_id: str, view: dict[str, Any]) -> None:
        self._maybe_fail()
        self.homes.append((user_id, view))

    def _maybe_fail(self) -> None:
        if self.failures:
            raise self.failures.pop(0)

    def describe(self) -> str:
        return "slack=twin"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
