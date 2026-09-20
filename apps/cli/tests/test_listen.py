"""The listener over the in-process API and a scripted channel: each change
is fetched and told as one line, deletes are told from memory, `--mine`
filters, and connection states reach stderr."""

import asyncio
import io
from collections.abc import AsyncIterator, Callable
from datetime import datetime

from api_support import OWNER
from cli_support import BOB, Stack

from tadas.apps.cli.listen import listen
from tadas.client.client import ApiClient
from tadas.client.envelopes import EntityChanged
from tadas.client.realtime import State
from tadas.client.types import TaskStatus, TaskView

CLOCK = datetime(2026, 9, 18, 9, 30, 0)


def test_every_change_becomes_one_line(stack: Stack) -> None:
    owner = stack.session_token(OWNER["email"], OWNER["password"])
    bob = stack.session_token(BOB["email"], BOB["password"])
    out, err = io.StringIO(), io.StringIO()

    async def scripted(
        client: ApiClient, on_state: Callable[[State], None]
    ) -> AsyncIterator[EntityChanged]:
        """Bob and the owner act while the owner listens; the changes are the
        pushes the socket would carry, read back from the event stream."""
        on_state("connecting")
        on_state("open")
        async with stack.client(bob) as as_bob, stack.client(owner) as as_owner:
            seq = 0  # a fresh org has no events yet
            ann, bobs = (await as_owner.me()).user.id, (await as_bob.me()).user.id

            async def latest() -> EntityChanged:
                nonlocal seq
                event = (await as_owner.events_after(seq))[-1]
                seq = event.seq
                return EntityChanged.of_event(event)

            task = await as_bob.create_task("Migrate DB")
            yield await latest()
            done = await as_owner.update_task(task.id, version=task.version, status=TaskStatus.done)
            yield await latest()
            given = await as_bob.update_task(task.id, version=done.version, assignee_id=ann)
            yield await latest()
            await as_bob.delete_task(task.id, given.version)
            on_state("reconnecting")  # as if the socket dropped here
            on_state("open")
            yield await latest()
            await as_owner.create_task("Write changelog", assignee_id=bobs)
            yield await latest()

    async def drive(mine: bool) -> None:
        async with stack.client(owner) as client:
            await listen(client, mine=mine, out=out, err=err, channel=scripted, clock=lambda: CLOCK)

    asyncio.run(drive(mine=False))
    assert out.getvalue().splitlines() == [
        "listening as Ann at Acme: the team's tasks",
        "09:30:00  Bob created a task: Migrate DB",
        "09:30:00  Ann completed a task: Migrate DB",
        "09:30:00  Bob assigned a task to Ann: Migrate DB",
        "09:30:00  Bob deleted a task: Migrate DB",
        "09:30:00  Ann created a task: Write changelog",
    ]
    assert err.getvalue().splitlines() == [
        "connection lost; reconnecting",
        "connected again; anything missed is replayed",
    ]

    out.truncate(0)
    out.seek(0)
    asyncio.run(drive(mine=True))
    lines = out.getvalue().splitlines()
    assert lines[0] == "listening as Ann at Acme: my tasks"
    # Bob's unassigned task is not Ann's, not even when she completes it, until
    # it is assigned to her; the changelog is Bob's.
    assert [line.split("  ", 1)[1] for line in lines[1:]] == [
        "Bob assigned a task to Ann: Migrate DB",
        "Bob deleted a task: Migrate DB",
    ]


def test_a_deleted_task_seen_before_the_listener_started_still_has_a_title(stack: Stack) -> None:
    owner = stack.session_token(OWNER["email"], OWNER["password"])
    out = io.StringIO()

    async def scripted(
        client: ApiClient, on_state: Callable[[State], None]
    ) -> AsyncIterator[EntityChanged]:
        async with stack.client(owner) as as_owner:
            await as_owner.delete_task(old.id, old.version)
            deleted = (await as_owner.events_after(0))[-1]
            # Created and deleted before the listener could read it: no title to tell.
            gone = await as_owner.create_task("Gone at once")
            await as_owner.delete_task(gone.id, gone.version)
            created, deleted_again = (await as_owner.events_after(deleted.seq))[-2:]
        for event in (deleted, created, deleted_again):
            yield EntityChanged.of_event(event)

    async def drive() -> None:
        async with stack.client(owner) as client:
            # "Old one" exists when the listener preloads, so its title is remembered.
            await listen(client, mine=False, out=out, channel=scripted, clock=lambda: CLOCK)

    async def prepare() -> TaskView:
        async with stack.client(owner) as as_owner:
            return await as_owner.create_task("Old one")

    old = asyncio.run(prepare())
    asyncio.run(drive())
    assert out.getvalue().splitlines()[1:] == [
        "09:30:00  Ann deleted a task: Old one",
        "09:30:00  Ann created a task: a task",
        "09:30:00  Ann deleted a task: a task",
    ]
