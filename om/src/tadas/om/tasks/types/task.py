from enum import Enum
from uuid import UUID

from tadas.om.base import Identifiable, SoftDeletable, Trackable


class TaskStatus(str, Enum):
    OPEN = "open"
    DONE = "done"


class TaskScope(str, Enum):
    """Which tasks a list shows. The org is the team."""

    MINE = "mine"  # assigned to the caller, or unassigned and created by the caller
    TEAM = "team"  # every task in the org


class Task(Identifiable, Trackable, SoftDeletable):
    title: str
    notes: str = ""
    status: TaskStatus = TaskStatus.OPEN
    assignee_id: UUID | None = None
    # Manual order of the open list, ascending; the top is the smallest. Done
    # tasks keep theirs but sort by updated_at instead.
    position: float = 0.0
    # Optimistic concurrency: the manager's copy increments it on every write,
    # and the write lands only when the stored row still has the version the
    # caller read. A snapshot that says another version is stale.
    version: int = 1
