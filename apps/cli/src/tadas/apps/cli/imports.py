"""The org's imports: how they are listed, how a short id names one, and
following one to its end. The import runs in the worker; the CLI opens the
one channel, reads the import once the channel is open (so a change made
before that read is in it, and one made after is pushed), and reads it
again on every push about it. A push is a hint and the import is the
truth. It stops when the import succeeded, parked, or failed."""

import sys
from collections.abc import AsyncIterable, Awaitable, Callable, Sequence
from datetime import UTC
from typing import TextIO
from uuid import UUID

from tadas.apps.cli.model import SHORT_ID, short_id
from tadas.client.client import ApiClient
from tadas.client.envelopes import EntityChanged
from tadas.client.realtime import Channel, State
from tadas.client.types import ImportView

ENTITY = "orchestration"
"""The entity an import's pushes name: `orchestrations.orchestration.updated`."""

RECENT = 20
"""How many of the org's newest imports `imports` lists and a short id is
resolved over."""

OpenChannel = Callable[
    [ApiClient, Callable[[State], None], Callable[[], Awaitable[None]]],
    AsyncIterable[EntityChanged],
]


def open_channel(
    client: ApiClient,
    on_state: Callable[[State], None],
    on_first_open: Callable[[], Awaitable[None]],
) -> AsyncIterable[EntityChanged]:
    return Channel(client, on_state=on_state, on_first_open=on_first_open)


class Stopped(Exception):
    """The import is no longer running; the view is how it stopped."""

    def __init__(self, view: ImportView) -> None:
        super().__init__(view.status.value)
        self.view = view


def is_running(view: ImportView) -> bool:
    return view.status.value == "running"


def progress(view: ImportView) -> str:
    """One line of how far an import is: created N of M, skipped K."""
    total = "?" if view.total is None else str(view.total)
    return f"created {view.created} of {total}, skipped {view.skipped}"


def outcome(view: ImportView) -> str:
    """The last line: how the import stopped, and what a person does next."""
    match view.status.value, view.park_reason, view.fail_reason:
        case "succeeded", _, _:
            return f"imported: {progress(view)}"
        case "parked", reason, _ if reason is not None and reason.value == "plan_limit":
            return (
                f"parked at row {view.cursor + 1}: the plan's active tasks are full "
                f"({progress(view)}). An owner or an admin can change the plan in the "
                "portal, under Settings, Billing, and the import goes on by itself; "
                f"or finish some tasks, then `tadas import --resume {short_id(view.id)}` "
                "or Resume on the tasks page"
            )
        case "failed", _, reason if reason is not None:
            return f"failed: {reason.value.replace('_', ' ')} ({progress(view)})"
        case status, _, _:
            return f"{status}: {progress(view)}"


def import_line(view: ImportView) -> str:
    started = view.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
    return f"{short_id(view.id)}  {view.status.value:<9}  {started}  {progress(view)}"


def import_table(views: Sequence[ImportView]) -> str:
    """The org's imports, newest first: id, status, when it started (UTC), how far."""
    header = f"{'ID':<{SHORT_ID}}  {'STATUS':<9}  {'STARTED (UTC)':<16}  PROGRESS"
    return "\n".join([header, *(import_line(v) for v in views)])


def resolve_import(reference: str, views: Sequence[ImportView]) -> ImportView:
    """A full id or a unique tail of one, over the org's recent imports."""
    wanted = reference.strip().lower()
    matches = [v for v in views if wanted and str(v.id).endswith(wanted)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LookupError(f"no recent import matches {reference!r}; `tadas imports` lists them")
    raise LookupError(f"{reference!r} matches more than one import; give more of the id")


async def follow(
    client: ApiClient,
    import_id: UUID,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
    channel: OpenChannel = open_channel,
) -> ImportView:
    """Prints a progress line each time the import moves; returns it stopped.
    The streams are the process's at the call, unless named."""
    out = out or sys.stdout
    err = err or sys.stderr
    shown: str | None = None

    def show(view: ImportView) -> None:
        nonlocal shown
        line = progress(view)
        if line != shown:
            print(line, file=out, flush=True)
            shown = line

    async def read() -> None:
        view = await client.task_import(import_id)
        if not is_running(view):
            raise Stopped(view)
        show(view)

    def on_state(state: State) -> None:
        if state == "reconnecting":
            print("connection lost; reconnecting", file=err, flush=True)

    changes = aiter(channel(client, on_state, read))
    try:
        async for change in changes:
            if change.entity == ENTITY and change.target_id == import_id:
                await read()
    except Stopped as stopped:
        return stopped.view
    finally:
        # The socket closes here, not whenever the loop's shutdown gets to it.
        close = getattr(changes, "aclose", None)
        if close is not None:
            await close()
    raise RuntimeError("the channel ended before the import stopped")
