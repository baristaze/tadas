"""A command's reply URL is a credential: whoever holds it posts into the
channel as the app. A reply leaves it in no log line and in no breadcrumb an
event carries. The SDK's retry line is not written at the deployed level, and
the breadcrumb of the reply's request names Slack's host alone."""

import io
import json
import logging
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import aiohttp.connector
import pytest
import sentry_sdk
from aiohttp.abc import AbstractResolver, ResolveResult
from sentry_sdk.envelope import Envelope
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.tracing_utils import add_http_breadcrumb
from sentry_sdk.transport import Transport

from tadas.infra.observability import (
    HTTP_CLIENT_LOGGERS,
    configure_error_reporting,
    configure_logging,
)
from tadas.integrations.slack import SlackFailed
from tadas.integrations.slack.web import SlackWebImpl

CAPABILITY = "S3CRETCAPABILITY"
REPLY_URL = f"https://hooks.slack.com/commands/T0ANN/12345/{CAPABILITY}"
log = logging.getLogger("tadas.tests.slack_reply")


class Captured(Transport):
    """Where the SDK sends an event in place of a tracker."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(dict(event))


@pytest.fixture
def tracker(monkeypatch: pytest.MonkeyPatch) -> Iterator[Captured]:
    """The SDK as `configure_error_reporting` sets it up, with the logging and
    the aiohttp integrations alone and every event kept here."""
    captured = Captured()
    init = sentry_sdk.init

    def kept_here(*args: Any, **options: Any) -> Any:
        return init(
            *args,
            **options,
            transport=captured,
            default_integrations=False,
            auto_enabling_integrations=False,
            integrations=[LoggingIntegration(), AioHttpIntegration()],
        )

    monkeypatch.setattr(sentry_sdk, "init", kept_here)
    with sentry_sdk.isolation_scope():
        configure_error_reporting("https://key@tracker.example.test/1", "test", "maintenance")
        try:
            yield captured
        finally:
            sentry_sdk.get_client().close()
            sentry_sdk.get_global_scope().set_client(None)


@contextmanager
def deployed() -> Iterator[io.StringIO]:
    """JSON lines with the root at INFO, as boot sets them in a deployed
    process. The Slack SDK's loggers and the HTTP clients' start from no
    level of their own, whatever ran before, and everything is put back
    after."""
    root = logging.getLogger()
    handlers, level = root.handlers, root.level
    names = {"slack_sdk", "slack_sdk.webhook.async_client", *HTTP_CLIENT_LOGGERS}
    clients = {name: logging.getLogger(name).level for name in names}
    for name in clients:
        logging.getLogger(name).setLevel(logging.NOTSET)
    root.handlers = []
    written, stderr = io.StringIO(), sys.stderr
    sys.stderr = written
    try:
        configure_logging("INFO", json_logs=True)
    finally:
        sys.stderr = stderr
    try:
        yield written
    finally:
        root.handlers = handlers
        root.setLevel(level)
        for name, was in clients.items():
            logging.getLogger(name).setLevel(was)


class Unreachable(AbstractResolver):
    """No name resolves, so each attempt fails to connect, and the SDK tries
    the reply a second time."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        raise OSError(f"{host} does not resolve")

    async def close(self) -> None:
        pass


async def test_a_reply_leaves_its_url_in_no_line_and_no_breadcrumb(
    tracker: Captured, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(aiohttp.connector, "DefaultResolver", Unreachable)
    client = SlackWebImpl("111.222", "client-secret", "signing-secret", timedelta(seconds=5))
    with deployed() as written:
        await client.start()
        try:
            with pytest.raises(SlackFailed):
                await client.respond(REPLY_URL, "Added: Water the plants")
        finally:
            await client.close()
        # A reply Slack answered: the breadcrumb the aiohttp integration adds
        # at the end of the request, with the data it gathers.
        answered = {"url": REPLY_URL, "http.method": "POST", "http.response.status_code": 200}
        add_http_breadcrumb(200, {**answered, "reason": "OK"})
        log.error("the next command failed")

    lines = written.getvalue()
    assert [json.loads(line)["message"] for line in lines.splitlines()] == [
        "the next command failed"
    ]
    (event,) = tracker.events
    (reply,) = [crumb for crumb in event["breadcrumbs"]["values"] if crumb["type"] == "http"]
    assert reply["data"] == {
        "http.method": "POST",
        "http.response.status_code": 200,
        "url": "https://hooks.slack.com",
    }
    assert CAPABILITY not in lines + json.dumps(event)
