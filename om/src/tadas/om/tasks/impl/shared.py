"""What more than one duty of the tasks manager calls: the room a plan
leaves for one more open task, and the rows a write of a task rides with.
Nothing here decides who may call: the callers authorize."""

from uuid import UUID

from tadas.om.billing.manager import EntitlementsInterface
from tadas.om.context import TenantContext
from tadas.om.outbox.types.row import OutboxRow, outbox_row
from tadas.om.slack import SlackManagerInterface
from tadas.om.slack.types.installation import SlackInstallationStatus
from tadas.om.tasks.rules import earliest_reminder_time, room_for
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.filter import TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope
from tadas.om.work.types.work_item import (
    SlackPostEvent,
    SlackPostPayload,
    TaskReminderPayload,
    WorkKind,
    work_row_kind,
)


async def room_left(
    storage: TasksStorageInterface, plans: EntitlementsInterface, ctx: TenantContext
) -> int | None:
    """How many more tasks the plan lets the org open now; None when it
    has no bound. Read at each step, so a plan raised between two steps
    lets the next one go further."""
    entitlements = await plans.get_entitlements(ctx)
    bound = entitlements.limits.active_tasks
    if bound is None:
        return None
    return room_for(bound, await storage.count_open_tasks(ctx.org_id, everyone(ctx)))


def everyone(ctx: TenantContext) -> TaskFilter:
    """Every open task of the org: what a plan's bound counts."""
    return TaskFilter(scope=TaskScope.TEAM, user_id=ctx.user_id)


def reminder_rows(ctx: TenantContext, task: Task) -> tuple[OutboxRow, ...]:
    """The work row that schedules the reminder of the task's due date,
    or none when it has none. The item waits in the queue until the
    first moment any zone's morning of that date comes, and its handler
    waits the rest from the person's zone
    (`reminders.get_due_reminder`)."""
    if task.due_on is None:
        return ()
    payload = TaskReminderPayload(not_before=earliest_reminder_time(task.due_on))
    kind = work_row_kind(WorkKind.TASK_REMINDER)
    return (outbox_row(ctx, kind, task.id, payload.model_dump(mode="json")),)


async def slack_rows(
    slack: SlackManagerInterface, ctx: TenantContext, task_id: UUID, event: SlackPostEvent
) -> tuple[OutboxRow, ...]:
    """The work row that posts the event to the org's Slack channel, or
    none when the org has not installed Slack, bound no channel, or its
    installation is broken."""
    installation = await slack.get_installation(ctx)
    if (
        installation is None
        or installation.channel_id is None
        or installation.status is not SlackInstallationStatus.OK
    ):
        return ()
    payload = SlackPostPayload(event=event)
    kind = work_row_kind(WorkKind.SLACK_POST)
    return (outbox_row(ctx, kind, task_id, payload.model_dump(mode="json")),)
