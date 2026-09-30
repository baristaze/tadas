from datetime import date
from uuid import UUID

from tadas.om.base import utcnow
from tadas.om.context import Permission, TenantContext
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import outbox_row
from tadas.om.slack import SlackManagerInterface
from tadas.om.tasks.impl.shared import slack_rows
from tadas.om.tasks.reminders import TasksRemindersManagerInterface
from tadas.om.tasks.rules import reminder_person, reminder_time
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.task import DueReminder, Task, TaskStatus
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.work.types.work_item import SlackPostEvent


class TasksRemindersManagerImpl(TasksRemindersManagerInterface):
    def __init__(
        self,
        storage: TasksStorageInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        slack: SlackManagerInterface,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._relay = relay
        self._slack = slack

    async def get_due_reminder(self, ctx: TenantContext, task_id: UUID) -> DueReminder | None:
        ctx.require(Permission.READ)
        task = await self._storage.read_task(ctx.org_id, task_id)
        if (
            task is None
            or task.deleted_at is not None
            or task.status is not TaskStatus.OPEN
            or task.due_on is None
            or task.reminded_at is not None
        ):
            return None
        zone = await self._tenancy.org.get_time_zone(ctx, reminder_person(task))
        return DueReminder(due_on=task.due_on, at=reminder_time(task.due_on, zone))

    async def fire_reminder(self, ctx: TenantContext, task_id: UUID, due_on: date) -> Task | None:
        ctx.require(Permission.WRITE)
        rows = (
            outbox_row(ctx, "tasks.task.reminded", task_id, {}),
            *await slack_rows(self._slack, ctx, task_id, SlackPostEvent.REMINDED),
        )
        reminded = await self._storage.mark_reminded(ctx.org_id, task_id, due_on, utcnow(), rows)
        if reminded is None:
            return None
        await self._relay.relay_all(ctx.org_id, rows)
        return reminded
