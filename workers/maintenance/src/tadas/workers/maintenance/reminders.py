"""The reminder handler: a task's due time came, so the team hears of it.

The item was scheduled by the write that set the due time and waited in the
queue until then. Whether it still means anything is the task's to say, in
one conditional write: open, living, still due at the time the item carries,
and not yet reminded. An edit that moved or cleared the due time, a task
finished or deleted meanwhile, and a second run of a reminder that went out
all make that write land nothing, and the item completes without a word."""

import logging

from tadas.om.base import utcnow
from tadas.om.opcontext import OpContext
from tadas.om.tasks import TasksManagerInterface
from tadas.om.work.types.handler import WorkHandlerInterface, WorkParked
from tadas.om.work.types.work_item import TaskReminderPayload, WorkItem

log = logging.getLogger(__name__)


class TaskReminderHandlerImpl(WorkHandlerInterface):
    def __init__(self, tasks: TasksManagerInterface) -> None:
        self._tasks = tasks

    async def handle(self, ctx: OpContext, item: WorkItem) -> None:
        payload = TaskReminderPayload.model_validate(item.payload)
        early = payload.not_before - utcnow()
        if early.total_seconds() > 0:
            # Claimed before its time (a clock ahead, a hand-back): wait it out.
            raise WorkParked("the reminder is not due yet", early)
        fired = await self._tasks.fire_reminder(ctx, item.target_id, payload.not_before)
        if fired is None:
            log.info("reminder %s for task %s is stale; nothing sent", item.id, item.target_id)
            return
        log.info("reminder %s for task %s went out", item.id, item.target_id)
