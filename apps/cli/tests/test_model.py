"""The pure rules: describing a change, the mine filter, short ids."""

from uuid import uuid4

import pytest

from tadas.apps.cli.model import describe, is_mine, resolve, short_id, task_table
from tadas.client.types import TaskStatus, TaskView

ME, BOB = uuid4(), uuid4()
NAMES = {ME: "Ann", BOB: "Bob"}


def name_of(user_id):
    return NAMES.get(user_id, "nobody")


def task(**changes) -> TaskView:
    base = {
        "id": uuid4(),
        "title": "Migrate DB",
        "notes": "",
        "status": TaskStatus.open,
        "assignee_id": None,
        "position": 0.0,
        "created_at": "2026-09-18T12:00:00Z",
        "updated_at": "2026-09-18T12:00:00Z",
        "created_by": ME,
        "deleted_at": None,
    }
    return TaskView.model_validate({**base, **changes})


def test_created_and_deleted_name_the_actor_and_the_title() -> None:
    t = task()
    assert describe("created", None, t, "Bob", name_of) == "Bob created a task: Migrate DB"
    assert describe("deleted", t, None, "Bob", name_of) == "Bob deleted a task: Migrate DB"
    assert describe("deleted", None, None, "Bob", name_of) == "Bob deleted a task: a task"


def test_an_update_names_the_first_difference_that_matters() -> None:
    before = task()
    done = before.model_copy(update={"status": TaskStatus.done})
    assert describe("updated", before, done, "Ann", name_of) == "Ann completed a task: Migrate DB"
    assert describe("updated", done, before, "Ann", name_of) == "Ann reopened a task: Migrate DB"
    renamed = before.model_copy(update={"title": "Migrate the DB"})
    assert (
        describe("updated", before, renamed, "Ann", name_of)
        == 'Ann renamed a task "Migrate DB" to "Migrate the DB"'
    )
    assigned = before.model_copy(update={"assignee_id": BOB})
    assert describe("updated", before, assigned, "Ann", name_of) == (
        "Ann assigned a task to Bob: Migrate DB"
    )
    assert (
        describe("updated", assigned, before, "Ann", name_of) == "Ann unassigned a task: Migrate DB"
    )
    noted = before.model_copy(update={"notes": "psql"})
    assert describe("updated", before, noted, "Ann", name_of) == (
        "Ann edited the notes of a task: Migrate DB"
    )
    moved = before.model_copy(update={"position": -1.0})
    assert describe("updated", before, moved, "Ann", name_of) == "Ann moved a task: Migrate DB"
    assert describe("updated", before, before, "Ann", name_of) == "Ann updated a task: Migrate DB"
    assert describe("updated", None, before, "Ann", name_of) == "Ann updated a task: Migrate DB"


def test_mine_is_assigned_to_me_or_unassigned_and_created_by_me() -> None:
    assert is_mine(task(), ME) is True
    assert is_mine(task(created_by=BOB), ME) is False
    assert is_mine(task(created_by=BOB, assignee_id=ME), ME) is True
    assert is_mine(task(assignee_id=BOB), ME) is False
    assert is_mine(None, ME) is False


def test_a_short_id_resolves_when_unique() -> None:
    a = task(id="0199a4c0-0000-7000-8000-000000000001")
    b = task(id="0199a4c0-0000-7000-8000-0000000000ab")
    assert resolve("0199a4c0-0000-7000-8000-000000000001", [a, b]) is a
    assert resolve("000000ab", [a, b]) is b
    assert resolve("00AB", [a, b]) is b
    with pytest.raises(LookupError, match="more than one"):
        resolve("", [a, b])
    with pytest.raises(LookupError, match="no task matches"):
        resolve("ffff", [a, b])
    assert short_id(a.id) == "00000001"


def test_the_table_has_a_header_and_one_line_per_task() -> None:
    a = task(id="0199a4c0-0000-7000-8000-000000000001", assignee_id=BOB)
    lines = task_table([a], name_of).splitlines()
    assert lines[0].startswith("ID        STATUS  ASSIGNEE")
    assert lines[1] == "00000001  open   Bob           Migrate DB"
