"""The reminders duty of the tasks manager: the reminder of a task's due
date."""

from abc import ABC, abstractmethod
from datetime import date
from uuid import UUID

from tadas.om.context import TenantContext
from tadas.om.tasks.types.task import DueReminder, Task


class TasksRemindersManagerInterface(ABC):
    """A delegate of `TasksManagerInterface`, reached as `tasks.reminders`.
    Every operation takes `TenantContext`."""

    @abstractmethod
    async def get_due_reminder(self, ctx: TenantContext, task_id: UUID) -> DueReminder | None:
        """The reminder the task is waiting for: its due date and the moment
        the reminder goes out, nine in the morning of that date in the time
        zone of the person the task is for (`tasks.rules.reminder_time`),
        read as the task and the person are now. None when the task waits for
        none: no due date, done, deleted, gone, or reminded already."""
        ...

    @abstractmethod
    async def fire_reminder(self, ctx: TenantContext, task_id: UUID, due_on: date) -> Task | None:
        """The reminder of the task's due date, when its moment has come:
        marks the task reminded and announces it (`tasks.task.reminded`), and
        asks for the Slack post when the org has a Slack channel bound, all in
        one write conditioned on the task still being open and due on `due_on`
        and not yet reminded. None when it no longer is, which is a reminder
        gone stale: nothing is written and nothing is announced."""
        ...
