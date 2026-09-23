"""The Slack client's own contract: Slack's answers become the three errors a
caller decides on, the real client translates the Web API's refusals into them
without the token in what it raises, a command's answer goes to Slack's own
address alone, the twin stays local and fails on request, and the off client
posts nothing."""

from datetime import timedelta
from typing import Any

import pytest
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from tadas.infra.exceptions import InfraException
from tadas.integrations.slack import (
    SlackChannelUnusable,
    SlackFailed,
    SlackNotConfigured,
    SlackRateLimited,
    error_for,
    is_response_url,
)
from tadas.integrations.slack.off import SlackOffImpl
from tadas.integrations.slack.twin import SlackTwinImpl
from tadas.integrations.slack.web import SlackWebImpl

TOKEN = "xoxb-000-000-not-a-real-token"


def test_slacks_answers_become_the_errors_a_caller_decides_on() -> None:
    limited = error_for("ratelimited", timedelta(seconds=7))
    assert isinstance(limited, SlackRateLimited) and limited.retry_after == timedelta(seconds=7)
    assert isinstance(error_for("ratelimited"), SlackRateLimited)
    for code in ("channel_not_found", "not_in_channel", "is_archived"):
        unusable = error_for(code)
        assert isinstance(unusable, SlackChannelUnusable) and unusable.slack_code == code
    other = error_for("internal_error")
    assert type(other) is SlackFailed and other.slack_code == "internal_error"
    assert isinstance(other, InfraException)


def test_only_slacks_own_address_answers_a_command() -> None:
    assert is_response_url("https://hooks.slack.com/commands/T0/1/abc")
    assert not is_response_url("https://hooks.slack.com.example.test/commands")
    assert not is_response_url("http://169.254.169.254/latest/meta-data/")


def refusal(status: int, error: str, headers: dict[str, str] | None = None) -> SlackApiError:
    response = AsyncSlackResponse(
        client=None,
        http_verb="POST",
        api_url="https://slack.com/api/chat.postMessage",
        req_args={},
        data={"ok": False, "error": error},
        headers=headers or {},
        status_code=status,
    )
    return SlackApiError(error, response)


async def started(monkeypatch: pytest.MonkeyPatch, answer: Any) -> SlackWebImpl:
    """The real client with its Web API call replaced: `answer` is raised when
    it is an exception and returned otherwise."""

    async def api_call(self: AsyncWebClient, method: str, **_: Any) -> Any:
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(AsyncWebClient, "api_call", api_call)
    client = SlackWebImpl(TOKEN, timedelta(seconds=5))
    await client.start()
    return client


async def test_the_web_client_returns_the_posts_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    client = await started(monkeypatch, {"ok": True, "ts": "1727000000.000100"})
    try:
        assert await client.post_message("C0TEAM", "hello") == "1727000000.000100"
        assert await client.reply_in_thread("C0TEAM", "1.0", "hi") == "1727000000.000100"
    finally:
        await client.close()


async def test_a_rate_limit_carries_the_wait_slack_named(monkeypatch: pytest.MonkeyPatch) -> None:
    client = await started(monkeypatch, refusal(429, "ratelimited", {"Retry-After": "12"}))
    try:
        with pytest.raises(SlackRateLimited) as raised:
            await client.post_message("C0TEAM", "hello")
        assert raised.value.retry_after == timedelta(seconds=12)
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (200, "not_in_channel", SlackChannelUnusable),
        (200, "channel_not_found", SlackChannelUnusable),
        (200, "is_archived", SlackChannelUnusable),
        (200, "invalid_auth", SlackFailed),
        (500, "", SlackFailed),
    ],
)
async def test_a_refusal_is_translated_and_never_carries_the_token(
    monkeypatch: pytest.MonkeyPatch, status: int, error: str, expected: type[Exception]
) -> None:
    client = await started(monkeypatch, refusal(status, error))
    try:
        with pytest.raises(expected) as raised:
            await client.post_message("C0TEAM", "hello")
        assert TOKEN not in str(raised.value) and raised.value.__cause__ is None
    finally:
        await client.close()


async def test_a_transport_failure_is_a_failure_worth_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = await started(monkeypatch, TimeoutError("read timed out"))
    try:
        with pytest.raises(SlackFailed) as raised:
            await client.publish_home("U0ANN", {"type": "home", "blocks": []})
        assert raised.value.slack_code == "TimeoutError"
    finally:
        await client.close()


async def test_the_web_client_refuses_a_foreign_response_url_before_any_request() -> None:
    client = SlackWebImpl(TOKEN, timedelta(seconds=5))
    with pytest.raises(SlackFailed) as raised:
        await client.respond("https://attacker.example.test/hook", "hi")
    assert raised.value.slack_code == "invalid_response_url"


async def test_the_web_client_is_not_used_before_start() -> None:
    with pytest.raises(RuntimeError):
        await SlackWebImpl(TOKEN, timedelta(seconds=5)).post_message("C0TEAM", "hello")


def test_the_twin_runs_locally_only() -> None:
    for environment in ("local", "test"):
        assert SlackTwinImpl(environment).describe() == "slack=twin"
    for environment in ("staging", "production"):
        with pytest.raises(ValueError):
            SlackTwinImpl(environment)


async def test_the_twin_records_what_it_was_asked_and_fails_on_request() -> None:
    twin = SlackTwinImpl("test")
    first = await twin.post_message("C0TEAM", "one")
    reply = await twin.reply_in_thread("C0TEAM", first, "two")
    assert [(p.text, p.thread_ts) for p in twin.posts] == [("one", None), ("two", first)]
    assert first != reply and first.startswith("twin.")

    twin.fail_next(error_for("not_in_channel"))
    with pytest.raises(SlackChannelUnusable):
        await twin.post_message("C0TEAM", "three")
    assert len(twin.posts) == 2
    await twin.post_message("C0TEAM", "four")
    assert len(twin.posts) == 3

    with pytest.raises(SlackFailed):
        await twin.respond("https://attacker.example.test/hook", "hi")
    await twin.respond("https://hooks.slack.com/commands/T0/1/abc", "hi")
    assert twin.responses == [("https://hooks.slack.com/commands/T0/1/abc", "hi")]


async def test_the_off_client_posts_nothing_and_says_why() -> None:
    off = SlackOffImpl()
    assert off.describe() == "slack=off"
    with pytest.raises(SlackNotConfigured):
        await off.post_message("C0TEAM", "hello")
    with pytest.raises(SlackNotConfigured):
        await off.respond("https://hooks.slack.com/commands/T0/1/abc", "hi")
