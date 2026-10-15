"""The tasks namespace's kinds: its kinds of work, which the business root
registers in `KINDS` below its marker (`work.kinds`), and its kinds of
long-running record, which it registers in `ORCHESTRATION_KINDS`
(`orchestrations.kinds`)."""

from enum import StrEnum

from tadas.om.context import Permission
from tadas.om.orchestrations.kinds import OrchestrationKindSpec
from tadas.om.tasks.types.work import (
    TaskCleanupInput,
    TaskImportInput,
    TaskReminderPayload,
    UnassignTasksPayload,
)
from tadas.om.work.kinds import WorkKindSpec


class TasksKind(StrEnum):
    """The names of the tasks namespace's kinds of work."""

    TASK_REMINDER = "TASK_REMINDER"  # a task's due date came: remind the team
    UNASSIGN_TASKS = "UNASSIGN_TASKS"  # a person who left: their open tasks go unassigned


class TasksOrchestrationKind(StrEnum):
    """The names of the tasks namespace's kinds of long-running record; the
    worker keys each one's step by the same name."""

    # Tasks made from the rows of a CSV file the org uploaded. A second
    # import starts beside the open one (ADR 1002).
    TASK_IMPORT = "task_import"
    TASK_CLEANUP = "task_cleanup"  # done tasks past an age archived; one record per org per day


TASKS_KINDS: tuple[WorkKindSpec, ...] = (
    WorkKindSpec(TasksKind.TASK_REMINDER, TaskReminderPayload, Permission.WRITE),
    # Only an account's deletion asks for this one, relayed from its own
    # commit: leaving is every person's right whatever their role, so no
    # route enqueues it, and the permission is the width of the handler.
    WorkKindSpec(TasksKind.UNASSIGN_TASKS, UnassignTasksPayload, Permission.WRITE),
)
"""The tasks namespace's kinds of work, each on the default lane."""

TASKS_ORCHESTRATION_KINDS: tuple[OrchestrationKindSpec, ...] = (
    OrchestrationKindSpec(TasksOrchestrationKind.TASK_IMPORT, TaskImportInput),
    OrchestrationKindSpec(TasksOrchestrationKind.TASK_CLEANUP, TaskCleanupInput),
)
"""The tasks namespace's kinds of long-running record."""
