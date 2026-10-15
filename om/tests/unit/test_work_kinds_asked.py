"""Every kind of work the tree asks for is one the root registers.

`WorkManagerImpl.enqueue` refuses a kind the registry (`root.KINDS`) does
not hold, and asks its caller for the permission the kind's spec gives; the
relay refuses a row of such a kind. So a kind the code asks for and the
registry does not hold is work nobody can start. The code asks in two ways:
an outbox row of the kind, `work_row_kind(<Namespace>Kind.X)`, which the
relay enqueues with no context, and a direct `enqueue` under a context.
This test reads both out of the source, outside the tests.
"""

import ast
import os
from collections.abc import Iterator
from pathlib import Path

from tadas.om.root import KINDS

ROOT = Path(__file__).resolve().parents[3]
LEFT_OUT = {"tests", ".venv", "node_modules", ".git"}
THE_QUEUE = "om/src/tadas/om/work/"
"""The namespace that holds `enqueue` itself."""


def calls() -> Iterator[tuple[str, ast.Call]]:
    """Every call in the tree, with where it is, outside the tests and what a
    tool installed."""
    for folder, folders, files in os.walk(ROOT):
        folders[:] = sorted(name for name in folders if name not in LEFT_OUT)
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = Path(folder) / name
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call):
                    yield f"{path.relative_to(ROOT).as_posix()}:{node.lineno}", node


def called(call: ast.Call) -> str:
    function = call.func
    return function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")


def kind_named(call: ast.Call) -> str | None:
    """The `X` of a `<Namespace>Kind.X` the call is handed, when it names one:
    a kind of work is named in capitals, its member's name and its value
    alike."""
    for argument in call.args:
        if (
            isinstance(argument, ast.Attribute)
            and isinstance(argument.value, ast.Name)
            and argument.value.id.endswith("Kind")
        ):
            return argument.attr
    return None


def test_every_kind_the_code_asks_for_is_registered() -> None:
    rows = {where: call for where, call in calls() if called(call) == "work_row_kind"}
    asked = {where: kind_named(call) for where, call in rows.items() if THE_QUEUE not in where}
    assert len(asked) >= 5, "the scan no longer sees the rows that ask for work"
    assert [where for where, name in asked.items() if name is None] == [], "a kind not named"
    unregistered = {
        where: name for where, name in asked.items() if name is not None and name not in KINDS
    }
    assert unregistered == {}


def test_the_code_asks_for_work_through_the_outbox_alone() -> None:
    """No code outside the queue's own namespace calls `enqueue`: every kind
    is asked for by a row its write landed, which the relay enqueues with no
    context and no permission to refuse. A direct enqueue added later is
    checked here first: its caller holds the permission its kind is asked
    for with, or the enqueue is refused."""
    direct = [
        where
        for where, call in calls()
        if called(call) == "enqueue" and not where.startswith(THE_QUEUE)
    ]
    assert direct == []
