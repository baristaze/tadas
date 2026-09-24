"""Reminders: a due time schedules one item that waits in the queue until
then; when it comes due the task is marked reminded and the org hears of it;
an edit that moves or clears the due time, and a finished or deleted task,
leave the scheduled item stale, and a stale item sends nothing."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from slack_support import build, claim, connect, make_task, owner_of, queued
from worker_support import fast_options

from tadas.infra.cache import CacheScope
from tadas.om.base import utcnow
from tadas.om.opcontext import OpContext
from tadas.om.tasks.types.task import TaskStatus
from tadas.om.work.types.handler import WorkHandlerInterface, WorkParked
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.loop import WorkerLoop
from tadas.workers.maintenance.reminders import TaskReminderHandlerImpl


async def reminded_kinds(container: WorkerContainer, ctx: OpContext) -> list[str]:
    events = await container.managers.events.get_events(ctx, 0, 100)
    return [event.kind for event in events if event.kind == "tasks.task.reminded"]


async def run_due(container: WorkerContainer) -> list[WorkItem]:
    """Claims every reminder that is due and runs it, as the loop would."""
    handler = TaskReminderHandlerImpl(container.managers.tasks)
    ran: list[WorkItem] = []
    while (claimed := await claim(container, WorkKind.TASK_REMINDER)) is not None:
        ctx, item = claimed
        await handler.handle(ctx, item)
        await container.managers.work.complete(ctx, item)
        ran.append(item)
    return ran


async def test_a_due_time_schedules_one_reminder_that_waits_until_then(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    due = utcnow() + timedelta(hours=1)
    task = await container.managers.tasks.create_task(ann, make_task(ann, remind_at=due))
    [item] = await queued(container, ann, WorkKind.TASK_REMINDER, task.id)
    assert item.available_at == due
    assert datetime.fromisoformat(item.payload["not_before"]) == due
    assert item.created_by == ann.user_id, "the person who set the due time asked for it"
    assert await claim(container, WorkKind.TASK_REMINDER) is None, "not before its time"
    plain = await container.managers.tasks.create_task(ann, make_task(ann, "no due time"))
    assert await queued(container, ann, WorkKind.TASK_REMINDER, plain.id) == []


async def test_the_reminder_goes_out_once_and_is_announced(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    due = utcnow() - timedelta(seconds=1)
    task = await container.managers.tasks.create_task(ann, make_task(ann, remind_at=due))
    [item] = await run_due(container)
    stored = await container.managers.tasks.get_task(ann, task.id)
    assert stored.reminded_at is not None and stored.version == task.version + 1
    assert await reminded_kinds(container, ann) == ["tasks.task.reminded"]
    # A second run of the same item, the at-least-once case, sends nothing.
    fired = await container.managers.tasks.fire_reminder(ann, task.id, due)
    assert fired is None
    assert await reminded_kinds(container, ann) == ["tasks.task.reminded"]
    assert item.target_id == task.id


async def test_moving_the_due_time_leaves_the_first_reminder_stale(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    tasks = container.managers.tasks
    first = utcnow() - timedelta(minutes=2)
    task = await tasks.create_task(ann, make_task(ann, remind_at=first))
    moved = task.model_copy(update={"remind_at": first + timedelta(minutes=1)})
    moved = await tasks.update_task(ann, moved, task.version)
    assert len(await queued(container, ann, WorkKind.TASK_REMINDER, task.id)) == 2
    assert len(await run_due(container)) == 2
    assert await reminded_kinds(container, ann) == ["tasks.task.reminded"], "the moved one alone"
    assert (await tasks.get_task(ann, task.id)).reminded_at is not None


async def test_a_new_due_time_after_a_reminder_is_reminded_again(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    tasks = container.managers.tasks
    task = await tasks.create_task(ann, make_task(ann, remind_at=utcnow() - timedelta(minutes=1)))
    await run_due(container)
    reminded = await tasks.get_task(ann, task.id)
    later = reminded.model_copy(update={"remind_at": utcnow() - timedelta(seconds=1)})
    again = await tasks.update_task(ann, later, reminded.version)
    assert again.reminded_at is None, "a new due time has not been reminded of"
    await run_due(container)
    assert len(await reminded_kinds(container, ann)) == 2


async def test_clearing_the_due_time_cancels_the_reminder(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    tasks = container.managers.tasks
    task = await tasks.create_task(ann, make_task(ann, remind_at=utcnow() - timedelta(seconds=1)))
    cleared = await tasks.update_task(ann, task.model_copy(update={"remind_at": None}), 1)
    assert cleared.remind_at is None
    assert len(await run_due(container)) == 1
    assert await reminded_kinds(container, ann) == []
    assert (await tasks.get_task(ann, task.id)).reminded_at is None


@pytest.mark.parametrize("ending", ["done", "deleted"])
async def test_a_finished_or_deleted_task_is_not_reminded(tmp_path: Path, ending: str) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    tasks = container.managers.tasks
    task = await tasks.create_task(ann, make_task(ann, remind_at=utcnow() - timedelta(seconds=1)))
    if ending == "done":
        await tasks.update_task(ann, task.model_copy(update={"status": TaskStatus.DONE}), 1)
    else:
        await tasks.delete_task(ann, task.id, 1)
    await run_due(container)
    assert await reminded_kinds(container, ann) == []


async def test_a_reminder_claimed_before_its_time_parks_until_then(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    due = utcnow() + timedelta(minutes=5)
    task = await container.managers.tasks.create_task(ann, make_task(ann, remind_at=due))
    [item] = await queued(container, ann, WorkKind.TASK_REMINDER, task.id)
    with pytest.raises(WorkParked) as parked:
        await TaskReminderHandlerImpl(container.managers.tasks).handle(ann, item)
    assert timedelta(minutes=4) < parked.value.resume_after <= timedelta(minutes=5)


async def test_a_reminder_asks_for_the_slack_post_when_a_channel_is_bound(
    tmp_path: Path,
) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    task = await container.managers.tasks.create_task(
        ann, make_task(ann, remind_at=utcnow() - timedelta(seconds=1))
    )
    await run_due(container)
    posts = await queued(container, ann, WorkKind.SLACK_POST, task.id)
    assert [item.payload["event"] for item in posts] == ["created", "reminded"]


class Parking(WorkHandlerInterface):
    async def handle(self, ctx: OpContext, item: WorkItem) -> None:
        raise WorkParked("slack said wait", timedelta(minutes=3))


async def test_the_loop_hands_a_parked_item_back_without_spending_an_attempt(
    tmp_path: Path,
) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    task = await container.managers.tasks.create_task(
        ann, make_task(ann, remind_at=utcnow() - timedelta(seconds=1))
    )
    loop = WorkerLoop(
        work=container.managers.work,
        outbox=container.managers.outbox,
        purges={},
        handlers={WorkKind.TASK_REMINDER: Parking()},
        topics=container.infra.get_topics(),
        liveness=container.infra.get_cache(CacheScope.WORKER_LIVENESS),
        options=fast_options(),
    )
    running = asyncio.create_task(loop.run())
    [item] = await queued(container, ann, WorkKind.TASK_REMINDER, task.id)
    storage = container.storage.get_work_storage()
    stored: WorkItem | None = None
    for _ in range(200):
        stored = await storage.read_item(ann.org_id, item.id)
        if stored is not None and stored.last_error:
            break
        await asyncio.sleep(0.01)
    loop.stop()
    await running
    assert stored is not None
    assert stored.status is WorkStatus.QUEUED and stored.attempts == 0
    assert stored.last_error == "parked: slack said wait"
    assert stored.available_at > utcnow() + timedelta(minutes=2)
