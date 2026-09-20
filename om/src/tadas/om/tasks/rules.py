"""Pure rules of the tasks namespace: which tasks a filter shows, where a
cursor cuts, and the arithmetic of the open list's manual order. Values in,
values out; no clock, no storage, no settings. The manager and both storage
impls call these; the relational impl spells the visibility and cursor rules
in SQL where one statement must decide, and names the rule it mirrors."""

from collections.abc import Sequence

from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
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


def is_after(task: Task, cursor: OpenTaskCursor) -> bool:
    """The open list is by position, top first; a task is on the next page
    when its (position, id) sorts strictly after the cursor's."""
    return (task.position, task.id) > (cursor.position, cursor.id)


def top_position(positions: Sequence[float]) -> float:
    """The position above every open task, given their positions ascending:
    one below the smallest, or 0.0 when the list is empty."""
    return positions[0] - 1.0 if positions else 0.0


def position_after(anchor: float, positions: Sequence[float]) -> float:
    """The position right after `anchor`, given the other open positions
    ascending: halfway to the next one, or one past the anchor when it is last."""
    following = [p for p in positions if p > anchor]
    return (anchor + following[0]) / 2 if following else anchor + 1.0


def is_between(anchor: float, position: float, positions: Sequence[float]) -> bool:
    """Whether `position` falls strictly after `anchor` and strictly before the
    open position that follows it, so the order it was chosen for is the order
    the list reads back. Halving a gap ends at float precision: once the
    midpoint equals a neighbour the `(position, id)` tie-break decides the
    order instead, and the list is renumbered."""
    following = [p for p in positions if p > anchor]
    return anchor < position and (not following or position < following[0])


def renumbered(count: int) -> list[float]:
    """The positions of a renumbered open list, top first: whole numbers, so
    every gap is wide again."""
    return [float(index) for index in range(count)]
