"""The Slack post handler: one message to the channel the org connected, for
a task created, completed, or reminded of.

Idempotent on the item's key: the post is recorded under it, and a run that
finds the record posts nothing, so a retried item never posts twice (a crash
between Slack's answer and the record is the one window left, and it costs a
duplicate line, never a lost one). The message is composed from the task as
it is when the item runs; the item carries no field of it.

Slack's answers decide the outcome. A rate limit parks the item until the
time Slack named, spending no attempt. A channel that is gone, archived, or
that the app is not in parks the connection: it is marked broken, which the
portal shows, and the item completes, since no retry fixes it. A missing bot
token is said once in the log and posts nothing. Anything else fails the
item, which retries with a growing delay."""

import logging

from tadas.integrations.slack import (
    SlackChannelUnusable,
    SlackInterface,
    SlackNotConfigured,
    SlackRateLimited,
)
from tadas.om.exceptions import NotFound
from tadas.om.opcontext import OpContext
from tadas.om.slack import SlackManagerInterface
from tadas.om.slack.types.connection import SlackConnectionStatus
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.types.task import Task
from tadas.om.work.types.handler import WorkHandlerInterface, WorkParked
from tadas.om.work.types.work_item import SlackPostEvent, SlackPostPayload, WorkItem

log = logging.getLogger(__name__)

LEADS: dict[SlackPostEvent, str] = {
    SlackPostEvent.CREATED: ":memo: New task",
    SlackPostEvent.COMPLETED: ":white_check_mark: Done",
    SlackPostEvent.REMINDED: ":alarm_clock: Reminder",
}


def escaped(text: str) -> str:
    """Slack's three control characters, escaped: a title is what a person
    typed, and `<!channel>` in one must not ping a channel."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def message_for(event: SlackPostEvent, task: Task) -> str:
    """The line the channel reads."""
    return f"{LEADS[event]}: *{escaped(task.title)}*"


class SlackPostHandlerImpl(WorkHandlerInterface):
    def __init__(
        self,
        tasks: TasksManagerInterface,
        slack: SlackManagerInterface,
        client: SlackInterface,
    ) -> None:
        self._tasks = tasks
        self._slack = slack
        self._client = client

    async def handle(self, ctx: OpContext, item: WorkItem) -> None:
        payload = SlackPostPayload.model_validate(item.payload)
        if await self._slack.read_post(ctx, item.idempotency_key) is not None:
            return  # posted by an earlier run of this item
        connection = await self._slack.get_connection(ctx)
        if connection is None or connection.status is not SlackConnectionStatus.OK:
            log.info("slack post %s dropped: the org has no working channel", item.id)
            return
        try:
            task = await self._tasks.get_task(ctx, item.target_id)
        except NotFound:
            log.info("slack post %s dropped: task %s is gone", item.id, item.target_id)
            return
        try:
            ts = await self._client.post_message(
                connection.channel_id, message_for(payload.event, task)
            )
        except SlackRateLimited as error:
            raise WorkParked("slack rate limited the post", error.retry_after) from None
        except SlackChannelUnusable as error:
            log.warning("slack channel of org %s is unusable: %s", ctx.org_id, error.slack_code)
            await self._slack.mark_broken(ctx, error.slack_code)
            return
        except SlackNotConfigured:
            log.warning("slack post %s dropped: no bot token is configured", item.id)
            return
        await self._slack.record_post(ctx, item.idempotency_key, connection.channel_id, ts)
