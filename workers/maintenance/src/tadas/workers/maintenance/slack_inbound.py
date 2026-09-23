"""What Slack sends, handled after it was acknowledged.

The Socket Mode process acknowledges every delivery on the socket first and
then puts it on the `slack` queue as an `InboundDelivery`; this module is the
other side of that queue. A delivery is a slash command (`/tadas ...`), an
app mention, or the App Home being opened. Each is handled here and then
deleted from the queue; one whose handling failed is left there and comes
back after its visibility timeout, and the hosted queue moves it to its
dead-letter queue after a few returns.

Handling twice is harmless. A task `/tadas add` creates takes an id derived
from the delivery's key and the time it was received, so the second create
meets the row already there. A link code works once. The replies are text
for the person who typed, and a second one says the same thing again."""

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from tadas.infra.observability import OUTCOMES
from tadas.infra.queues import Queues, QueuesInterface
from tadas.integrations.slack import (
    SlackChannelUnusable,
    SlackError,
    SlackFailed,
    SlackInterface,
    SlackRateLimited,
)
from tadas.om.base import derived_id, new_id, utcnow
from tadas.om.exceptions import NotFound, PlatformException, SlackChannelTaken
from tadas.om.opcontext import AppContext, RequestContext
from tadas.om.slack import SlackManagerInterface
from tadas.om.slack.types.connection import SlackConnectionStatus
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.types.task import Task

log = logging.getLogger(__name__)

SLACK_NAMESPACE = uuid.UUID("5a1ac000-7ada-5000-8000-000000000000")
"""The UUID v5 namespace a Slack delivery's key is derived in."""

TITLE_LIMIT = 500
"""The longest title a task takes, as the API's own limit."""


class InboundDelivery(BaseModel):
    """One delivery from Slack, as the Socket Mode process queued it: its key,
    when it arrived, the envelope's type, and Slack's own payload."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    key: uuid.UUID
    received_at: datetime
    type: str  # "slash_commands", "events_api", ...
    payload: dict[str, Any]


def delivery_key(envelope_type: str, envelope_id: str, payload: dict[str, Any]) -> uuid.UUID:
    """The producer's idempotency key of a delivery: a UUID v5 over the
    provider's name and its delivery id. An event keeps its `event_id` across
    Slack's retries, which arrive in new envelopes, so that is its id; a
    command has only its envelope."""
    event_id = payload.get("event_id") if envelope_type == "events_api" else None
    return uuid.uuid5(SLACK_NAMESPACE, f"slack:{event_id or envelope_id}")


class Verb(StrEnum):
    HELP = "help"
    LINK = "link"
    ADD = "add"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Command:
    verb: Verb
    argument: str = ""


def parse_command(text: str) -> Command:
    """`/tadas <verb> <argument>`: `add <title>`, `link <code>`, `help`. An
    empty command is help; a verb it does not know, or `add` and `link` with
    nothing after them, is unknown, which answers with the usage too."""
    verb, _, rest = text.strip().partition(" ")
    verb, rest = verb.lower(), rest.strip()
    if verb in ("", "help"):
        return Command(Verb.HELP)
    if verb == "add" and rest:
        return Command(Verb.ADD, rest)
    if verb == "link" and rest:
        return Command(Verb.LINK, rest)
    return Command(Verb.UNKNOWN, text.strip())


USAGE = "\n".join(
    [
        "*Tadas* keeps your team's to-do list.",
        "• `/tadas add <title>` adds a task to the org this channel is connected to",
        "• `/tadas link <code>` connects this channel to an org: an owner or an admin"
        " gets the code in Tadas, under Settings, Slack",
        "• `/tadas help` shows this",
        "Reminders, new tasks, and finished ones are posted in the connected channel.",
    ]
)

NOT_CONNECTED = (
    "This channel is not connected to a Tadas org yet. An owner or an admin opens"
    " Settings in Tadas, clicks *Connect Slack*, and types `/tadas link <code>` here."
)

INVITE = "@tadas is not in this channel yet, so it cannot post here: type `/invite @tadas`."

CONNECTED = (
    ":link: This channel is connected to Tadas. Reminders and task updates will appear here."
)


def home_view() -> dict[str, Any]:
    """The App Home: how to connect a channel and what the commands do."""
    return {
        "type": "home",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "Tadas"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": USAGE}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Connect a channel*\n1. In Tadas, open Settings and click"
                    " *Connect Slack*.\n2. In the channel, type `/invite @tadas`, then"
                    " `/tadas link <code>` with the code Tadas showed.",
                },
            },
        ],
    }


class SlackInboundHandler:
    """What each kind of delivery does. Holds nothing per delivery."""

    def __init__(
        self,
        slack: SlackManagerInterface,
        tasks: TasksManagerInterface,
        client: SlackInterface,
        app: AppContext,
    ) -> None:
        self._slack = slack
        self._tasks = tasks
        self._client = client
        self._app = app

    async def handle(self, delivery: InboundDelivery) -> None:
        if delivery.type == "slash_commands":
            await self._command(delivery)
        elif delivery.type == "events_api":
            await self._event(delivery.payload.get("event") or {})
        else:
            log.info("slack delivery %s of type %s ignored", delivery.key, delivery.type)

    def _request(self) -> RequestContext:
        return RequestContext(request_id=new_id(), app=self._app)

    async def _command(self, delivery: InboundDelivery) -> None:
        payload = delivery.payload
        team_id = str(payload.get("team_id", ""))
        channel_id = str(payload.get("channel_id", ""))
        response_url = str(payload.get("response_url", ""))
        command = parse_command(str(payload.get("text", "")))
        if command.verb in (Verb.HELP, Verb.UNKNOWN):
            await self._client.respond(response_url, USAGE)
        elif command.verb is Verb.LINK:
            answer = await self._link(
                command.argument, team_id, channel_id, str(payload.get("user_id", ""))
            )
            await self._client.respond(response_url, answer)
        else:
            answer = await self._add(delivery, command.argument, team_id, channel_id)
            await self._client.respond(response_url, answer)

    async def _link(self, code: str, team_id: str, channel_id: str, slack_user: str) -> str:
        try:
            await self._slack.redeem_link_code(
                self._request(), code, team_id, channel_id, slack_user
            )
        except NotFound:
            return "That code is unknown, used, or expired. Get a new one in Tadas, under Settings."
        except SlackChannelTaken:
            return "This channel is connected to another Tadas org. Disconnect it there first."
        found = await self._slack.channel_context(self._request(), team_id, channel_id)
        if found is None:
            return "The channel could not be connected; try again with a new code."
        ctx, _ = found
        # The first post says the channel is connected, and says whether the
        # app can post here at all: a channel it was never invited to refuses.
        try:
            await self._client.post_message(channel_id, CONNECTED)
        except SlackChannelUnusable as error:
            await self._slack.mark_broken(ctx, error.slack_code)
            return f"Connected. {INVITE} Then run `/tadas link` again with a new code."
        return "Connected. Try `/tadas add <title>`."

    async def _add(
        self, delivery: InboundDelivery, title: str, team_id: str, channel_id: str
    ) -> str:
        found = await self._slack.channel_context(self._request(), team_id, channel_id)
        if found is None:
            return NOT_CONNECTED
        ctx, connection = found
        title = title[:TITLE_LIMIT]
        now = utcnow()
        task = Task(
            id=derived_id(delivery.key, delivery.received_at),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            title=title,
        )
        created = await self._tasks.create_task(ctx, task)
        answer = f"Added: *{created.title}*"
        if connection.status is not SlackConnectionStatus.OK:
            answer += f"\n{INVITE} Then run `/tadas link` again with a new code."
        return answer

    async def _event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "app_mention":
            channel = str(event.get("channel", ""))
            thread = str(event.get("thread_ts") or event.get("ts") or "")
            await self._client.reply_in_thread(channel, thread, USAGE)
        elif kind == "app_home_opened" and event.get("tab", "home") == "home":
            await self._client.publish_home(str(event.get("user", "")), home_view())
        else:
            log.info("slack event %s ignored", kind)


class InboundOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    batch: int = 10
    wait: timedelta = timedelta(seconds=10)
    visibility: timedelta = timedelta(seconds=60)
    error_backoff: timedelta = timedelta(seconds=5)
    idle: timedelta = timedelta(seconds=1)
    """The pause after an empty receive. The hosted queue's long poll already
    waits; a queue that answers empty at once (the in-process twin) would
    otherwise spin."""


def settled(error: SlackError | PlatformException) -> bool:
    """Whether a refusal ends the delivery: a platform refusal of the request
    (a 4xx) and a Slack answer about the channel or the token do; a rate
    limit, a transport failure, and a platform that cannot serve now (a 5xx)
    are worth another run."""
    if isinstance(error, PlatformException):
        return error.http_status < 500
    return not isinstance(error, SlackRateLimited | SlackFailed)


class SlackInboundConsumer:
    """The loop over the `slack` queue: receive, handle, delete. A delivery
    that does not parse is deleted with a log line, since no retry parses it;
    one whose handling raised stays for the queue to hand back."""

    def __init__(
        self, queues: QueuesInterface, handler: SlackInboundHandler, options: InboundOptions
    ) -> None:
        self._queues = queues
        self._handler = handler
        self._options = options
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        while not self._stopping.is_set():
            try:
                received = await self.poll_once()
            except Exception:
                log.exception("slack inbound: receive failed")
                OUTCOMES.labels(subsystem="slack_inbound", outcome="receive_error").inc()
                await self._pause(self._options.error_backoff)
                continue
            if received == 0:
                await self._pause(self._options.idle)

    async def _pause(self, pause: timedelta) -> None:
        """Waits out `pause`, or less when a stop arrives meanwhile."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=pause.total_seconds())

    async def poll_once(self) -> int:
        """One receive and every delivery it returned; how many it received."""
        messages = await self._queues.receive(
            Queues.SLACK, self._options.batch, self._options.wait, self._options.visibility
        )
        for message in messages:
            try:
                delivery = InboundDelivery.model_validate_json(message.body)
            except ValidationError:
                log.error("slack inbound: message %s does not parse; dropped", message.id)
                OUTCOMES.labels(subsystem="slack_inbound", outcome="malformed").inc()
                await self._queues.delete(Queues.SLACK, message.receipt)
                continue
            try:
                await self._handler.handle(delivery)
            except (SlackError, PlatformException) as error:
                if not settled(error):
                    log.warning(
                        "slack inbound: %s met %s; the queue hands it back", delivery.key, error
                    )
                    OUTCOMES.labels(subsystem="slack_inbound", outcome="failed").inc()
                    continue
                # A refusal no retry changes is said in the log; the delivery is done.
                log.warning("slack inbound: %s answered %s", delivery.key, error)
                OUTCOMES.labels(subsystem="slack_inbound", outcome="refused").inc()
            except Exception:
                log.exception("slack inbound: %s failed; the queue hands it back", delivery.key)
                OUTCOMES.labels(subsystem="slack_inbound", outcome="failed").inc()
                continue
            await self._queues.delete(Queues.SLACK, message.receipt)
            OUTCOMES.labels(subsystem="slack_inbound", outcome="handled").inc()
        return len(messages)
