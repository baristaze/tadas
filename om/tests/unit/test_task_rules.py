from uuid import UUID

from contracts.task_storage import make_task

from tadas.om.base import new_id
from tadas.om.tasks.rules import is_before, is_visible, position_after, top_position
from tadas.om.tasks.types.filter import TaskCursor, TaskFilter
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


def test_placement_arithmetic() -> None:
    assert top_position([]) == 0.0
    assert top_position([-1.0, 2.0]) == -2.0
    assert position_after(1.0, [1.0, 2.0]) == 1.5
    assert position_after(2.0, [1.0, 2.0]) == 3.0
    assert position_after(0.5, []) == 1.5
