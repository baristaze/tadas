"""The real client: the Slack Web API under the bot token, over aiohttp.
One session for the life of the process, opened at start and shared by the
Web API client and the command replies, every call under the timeout from
settings."""

import logging
from datetime import timedelta
from typing import Any

import aiohttp
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.webhook.async_client import AsyncWebhookClient

from tadas.integrations.slack import (
    SlackError,
    SlackFailed,
    SlackInterface,
    error_for,
    is_response_url,
)

log = logging.getLogger(__name__)


class SlackWebImpl(SlackInterface):
    def __init__(self, bot_token: str, timeout: timedelta) -> None:
        self._token = bot_token
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        self._client: AsyncWebClient | None = None

    def _web(self) -> AsyncWebClient:
        if self._client is None:
            raise RuntimeError("the Slack client is used before start()")
        return self._client

    async def post_message(self, channel_id: str, text: str) -> str:
        response = await self._call("chat.postMessage", channel=channel_id, text=text)
        return str(response["ts"])

    async def reply_in_thread(self, channel_id: str, thread_ts: str, text: str) -> str:
        response = await self._call(
            "chat.postMessage", channel=channel_id, thread_ts=thread_ts, text=text
        )
        return str(response["ts"])

    async def respond(self, response_url: str, text: str) -> None:
        if not is_response_url(response_url):
            raise SlackFailed("invalid_response_url", "a response_url that is not Slack's")
        hook = AsyncWebhookClient(
            response_url, session=self._session, timeout=int(self._timeout.total_seconds())
        )
        try:
            answer = await hook.send(text=text, response_type="ephemeral")
        except Exception as error:
            raise SlackFailed(type(error).__name__, str(error)) from error
        if answer.status_code >= 400:
            raise SlackFailed(f"http_{answer.status_code}", answer.body)

    async def publish_home(self, user_id: str, view: dict[str, Any]) -> None:
        await self._call("views.publish", user_id=user_id, view=view)

    async def _call(self, method: str, **params: Any) -> Any:
        """One Web API call, its refusals translated into the errors a caller
        decides on; the token never appears in what is raised or logged."""
        try:
            return await self._web().api_call(method, json=params)
        except SlackApiError as error:
            response = error.response
            code = str(response.get("error") or f"http_{response.status_code}")
            retry_after: timedelta | None = None
            if response.status_code == 429:
                header = response.headers.get("Retry-After") or response.headers.get("retry-after")
                retry_after = timedelta(seconds=int(header or 30))
            raise error_for(code, retry_after) from None
        except SlackError:
            raise
        except Exception as error:
            raise SlackFailed(type(error).__name__, str(error)) from error

    def describe(self) -> str:
        return "slack=web"

    async def start(self) -> None:
        seconds = int(self._timeout.total_seconds())
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=seconds))
        self._client = AsyncWebClient(token=self._token, session=self._session, timeout=seconds)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
        self._session = None
        self._client = None
