"""The tasks namespace's types: tasks, their lists and counts, a change of
many at once, and a CSV import."""

from tadas.client.schema.tasks import (
    BulkAction,
    BulkTasksView,
    ImportPageView,
    ImportView,
    TaskCountView,
    TaskPageView,
    TaskScope,
    TaskStatus,
    TaskView,
)

__all__ = [
    "BulkAction",
    "BulkTasksView",
    "ImportPageView",
    "ImportView",
    "TaskCountView",
    "TaskPageView",
    "TaskScope",
    "TaskStatus",
    "TaskView",
]
