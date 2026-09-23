"""The client a deployed process holds when no bot token is configured: it
posts nothing and says why, so a missing secret is a log line and never a
queue of retries."""

from typing import Any

from tadas.integrations.slack import SlackInterface, SlackNotConfigured


class SlackOffImpl(SlackInterface):
    async def post_message(self, channel_id: str, text: str) -> str:
        raise SlackNotConfigured()

    async def reply_in_thread(self, channel_id: str, thread_ts: str, text: str) -> str:
        raise SlackNotConfigured()

    async def respond(self, response_url: str, text: str) -> None:
        raise SlackNotConfigured()

    async def publish_home(self, user_id: str, view: dict[str, Any]) -> None:
        raise SlackNotConfigured()

    def describe(self) -> str:
        return "slack=off"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
