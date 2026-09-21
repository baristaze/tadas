import random
from uuid import UUID

from contracts.task_storage import make_task

from tadas.om.base import new_id
from tadas.om.tasks.rules import (
    Place,
    follows,
    is_after,
    is_before,
    is_between,
    is_visible,
    position_after,
    renumbered,
    top_position,
)
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.task import TaskScope


def mine(user_id: UUID) -> TaskFilter:
    return TaskFilter(scope=TaskScope.MINE, user_id=user_id)


def test_mine_is_assigned_to_me_or_unassigned_and_created_by_me() -> None:
    me, other = new_id(), new_id()
    assert is_visible(make_task(created_by=me), mine(me))
    assert is_visible(make_task(created_by=other, assignee_id=me), mine(me))
    assert not is_visible(make_task(created_by=me, assignee_id=other), mine(me))
    assert not is_visible(make_task(created_by=other), mine(me))
    assert is_visible(make_task(created_by=other), TaskFilter(scope=TaskScope.TEAM, user_id=me))


def test_the_cursor_cuts_strictly_before_by_updated_at_then_id() -> None:
    task = make_task()
    at = TaskCursor(updated_at=task.updated_at, id=task.id)
    assert not is_before(task, at)
    assert is_before(task, TaskCursor(updated_at=task.updated_at, id=UUID(int=task.id.int + 1)))
    assert not is_before(task, TaskCursor(updated_at=task.updated_at, id=UUID(int=task.id.int - 1)))


# Three ids in ascending order, so a place is written as (position, id) and
# two places that tie on position are told apart the way the list tells them.
A, B, C = (UUID(int=n) for n in (10, 20, 30))


def test_placement_arithmetic() -> None:
    assert top_position([]) == 0.0
    assert top_position([(-1.0, A), (2.0, B)]) == -2.0
    assert position_after((1.0, A), [(1.0, A), (2.0, B)]) == 1.5
    assert position_after((2.0, B), [(1.0, A), (2.0, B)]) == 3.0
    assert position_after((0.5, A), []) == 1.5


def test_a_tie_with_the_anchor_is_the_next_place_and_leaves_no_room() -> None:
    """Two open tasks can share a position: two creates that read the same list,
    or two moves after the same last anchor. The list orders them by id, so the
    task that ties with the anchor and follows it on id is what a task dropped
    after the anchor must land before. Reading positions alone, the next place
    after A was C at 6.0, the midpoint 5.5 landed past B, and "after A" read
    back as A, B, moved. There is no position strictly between A and B, so the
    placement asks for a renumber instead of tying too."""
    tied = [(5.0, A), (5.0, B), (6.0, C)]
    assert position_after((5.0, A), tied) == 5.0
    assert not is_between((5.0, A), 5.0, tied)
    # After the last of a tie there is room, as after any last place.
    assert position_after((5.0, B), [(5.0, A), (5.0, B)]) == 6.0
    assert is_between((5.0, B), 6.0, [(5.0, A), (5.0, B)])


def test_a_gap_is_open_until_halving_meets_a_neighbour() -> None:
    assert is_between((1.0, A), 1.5, [(1.0, A), (2.0, B)])
    assert is_between((2.0, B), 3.0, [(1.0, A), (2.0, B)]), "past the last there is room"
    assert not is_between((1.0, A), 1.0, [(1.0, A), (2.0, B)]), "the midpoint rounded to the anchor"
    assert not is_between((1.0, A), 2.0, [(1.0, A), (2.0, B)]), "the midpoint rounded to the next"
    # Halving from a gap of one meets the anchor after fifty-odd steps.
    anchor, following = (-1.0, A), (0.0, B)
    steps = 0
    while is_between(anchor, position_after(anchor, [anchor, following]), [anchor, following]):
        following = (position_after(anchor, [anchor, following]), B)
        steps += 1
    assert 50 <= steps <= 54
    assert renumbered(3) == [0.0, 1.0, 2.0] and renumbered(0) == []


def test_is_after_cuts_the_open_list_by_position_then_id() -> None:
    task = make_task(position=2.0)
    at = OpenTaskCursor(position=task.position, id=task.id)
    assert not is_after(task, at), "the cursor's own task is on the previous page"
    assert is_after(task, OpenTaskCursor(position=1.0, id=task.id))
    assert not is_after(task, OpenTaskCursor(position=3.0, id=task.id))
    assert is_after(task, OpenTaskCursor(position=2.0, id=UUID(int=task.id.int - 1)))
    assert not is_after(task, OpenTaskCursor(position=2.0, id=UUID(int=task.id.int + 1)))


def test_the_one_place_a_bounded_read_returns_decides_as_every_place_does() -> None:
    """A placement reads one place, not the open list: the top place for a task
    placed on top, the first place that follows the anchor for a move. Over
    lists with ties and with tight gaps, the rules answer the same from that
    one place as from every place."""
    rng = random.Random(29)
    for _ in range(500):
        positions = [float(rng.choice([0, 1, 1, 2, 2.5, 3])) for _ in range(rng.randint(0, 8))]
        places: list[Place] = sorted((p, new_id()) for p in positions)
        top = places[:1]
        assert top_position(top) == top_position(places)
        for anchor in [*places, (rng.choice([0.5, 1.0, 4.0]), new_id())]:
            following = [p for p in places if p != anchor and follows(p, anchor)][:1]
            others = [p for p in places if p != anchor]
            position = position_after(anchor, others)
            assert position_after(anchor, following) == position
            assert is_between(anchor, position, following) == is_between(anchor, position, others)


def test_follows_compares_the_pair() -> None:
    low, high = sorted((new_id(), new_id()))
    assert follows((1.0, high), (1.0, low))
    assert not follows((1.0, low), (1.0, high))
    assert not follows((1.0, low), (1.0, low))
    assert follows((2.0, low), (1.0, high))
