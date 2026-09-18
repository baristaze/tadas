"""Pure rules of the tasks namespace: which tasks a filter shows, where a
cursor cuts, and the arithmetic of the open list's manual order. Values in,
values out; no clock, no storage, no settings. The manager and both storage
impls call these; the relational impl spells the visibility and cursor rules
in SQL where one statement must decide, and names the rule it mirrors."""

from collections.abc import Sequence

from tadas.om.tasks.types.filter import TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope


def is_visible(task: Task, criterion: TaskFilter) -> bool:
    """`team` shows every task; `mine` shows a task assigned to the person, or
    unassigned and created by them."""
    if criterion.scope is TaskScope.TEAM:
        return True
    if task.assignee_id is not None:
        return task.assignee_id == criterion.user_id
    return task.created_by == criterion.user_id


def is_before(task: Task, cursor: TaskCursor) -> bool:
    """The done list is newest first; a task is on the next page when its
    (updated_at, id) sorts strictly before the cursor's."""
    return (task.updated_at, task.id) < (cursor.updated_at, cursor.id)


def top_position(positions: Sequence[float]) -> float:
    """The position above every open task, given their positions ascending:
    one below the smallest, or 0.0 when the list is empty."""
    return positions[0] - 1.0 if positions else 0.0


def position_after(anchor: float, positions: Sequence[float]) -> float:
    """The position right after `anchor`, given the other open positions
    ascending: halfway to the next one, or one past the anchor when it is last."""
    following = [p for p in positions if p > anchor]
    return (anchor + following[0]) / 2 if following else anchor + 1.0
