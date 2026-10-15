"""The shapes the tasks namespace's kinds carry (`tasks.kinds`): the payload
of each kind of work, and the input of each kind of long-running record."""

from datetime import datetime
from uuid import UUID

from tadas.om.base import OmBase
from tadas.om.work.types.work_item import ScheduledPayload


class TaskReminderPayload(ScheduledPayload):
    """The first moment any person's reminder of the task's due date can go
    out, as `not_before` (`tasks.rules.earliest_reminder_time`). The payload
    carries no date: the handler reads the task's date and the person's time
    zone when it runs, waits for their morning, and fires only while the task
    is still due on that date. An edit that moved or cleared the date leaves
    an item that completes without a word."""


class UnassignTasksPayload(OmBase):
    """The item's target is the user who left the org, and it runs under
    their name on the service role: their open tasks there are unassigned,
    whatever role they held (ADR 1011)."""


class TaskImportInput(OmBase):
    """The CSV file the import reads, uploaded through the media namespace."""

    file_id: UUID


class TaskCleanupInput(OmBase):
    """Done tasks last changed before `before` are archived. The cutoff is
    fixed when the day's record opens (`older_than_days` before then), so
    every step of one record asks the same question."""

    older_than_days: int
    before: datetime
