"""Pure rules of the tasks namespace: which tasks a filter shows, where a
cursor cuts, and the arithmetic of the open list's manual order. Values in,
values out; no clock, no storage, no settings. The manager and both storage
impls call these; the relational impl spells the visibility, cursor, and
follows rules in SQL where one statement must decide, and names the rule it
mirrors."""

from collections.abc import Sequence
from uuid import UUID

from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope

Place = tuple[float, UUID]
"""Where an open task sits: its position and its id, the pair the open list is
ordered by. A position is not unique — two writers that read the same list
place two tasks at the same one — so every rule below compares the pair, the
way `is_after` and the storage's ordering do. Which place follows the anchor
is decided on the pair; whether there is room between them is decided on the
positions alone, so a placement never adds a tie of its own."""


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


def top_position(places: Sequence[Place]) -> float:
    """The position above every open task, given their places ascending:
    one below the smallest, or 0.0 when the list is empty. Only the first
    place is read, so the top place alone is enough."""
    return places[0][0] - 1.0 if places else 0.0


def follows(place: Place, anchor: Place) -> bool:
    """Whether `place` comes after `anchor` in the order the open list reads:
    the pair compared, so a place that ties with the anchor on position and
    follows it on id is after it."""
    return place > anchor


def _following(anchor: Place, places: Sequence[Place]) -> Place | None:
    """The open place right after `anchor` in the order the list reads. A place
    that ties with the anchor on position and follows it on id is after it;
    reading positions alone would skip over it to the next larger position and
    place a task the caller asked to follow the anchor behind its twin. The
    places may be every open place or only the first one after the anchor;
    the answer is the same."""
    after = [place for place in places if follows(place, anchor)]
    return min(after) if after else None


def position_after(anchor: Place, places: Sequence[Place]) -> float:
    """The position right after `anchor`, given the other open places: halfway
    to the one that follows it, or one past the anchor when it is last."""
    following = _following(anchor, places)
    return (anchor[0] + following[0]) / 2 if following is not None else anchor[0] + 1.0


def is_between(anchor: Place, position: float, places: Sequence[Place]) -> bool:
    """Whether `position` falls strictly after the anchor's and strictly before
    that of the place which follows it, so the order it was chosen for is the
    order the list reads back and no two open tasks share it. Halving a gap
    ends at float precision, and so does a position that already ties with its
    neighbour: once the midpoint equals either of them there is no room left
    and the list is renumbered."""
    following = _following(anchor, places)
    return anchor[0] < position and (following is None or position < following[0])


def renumbered(count: int) -> list[float]:
    """The positions of a renumbered open list, top first: whole numbers, so
    every gap is wide again."""
    return [float(index) for index in range(count)]
