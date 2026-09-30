"""Long-running records in the worker, over the import: a record started, its
steps claimed and run from the queue until it succeeds, the plan's bound
parking it and the processor's delivery of a higher plan waking it, a step
that errors retried by the queue from its cursor and failed as a defect on its
last attempt, and a step for a record that no longer runs doing nothing. Then
the sweep opening the day's cleanup, whose steps archive the old done tasks,
and the sweep respacing a run of long ranks."""

from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

import pytest
from slack_support import on_team, owner_of
from test_billing_work import checkout, consumer_of, queued
from worker_support import build_container, request, sign_in, start_import

from tadas.om.base import new_id, utcnow
from tadas.om.billing.types.plan import Plan
from tadas.om.context import TenantContext
from tadas.om.orchestrations.types.orchestration import (
    FailReason,
    Orchestration,
    OrchestrationKind,
    OrchestrationStatus,
    ParkReason,
)
from tadas.om.tasks.rules import needs_respace
from tadas.om.tasks.types.filter import TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus
from tadas.om.work.types.handler import WorkHandlerInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.main import build_loop
from tadas.workers.maintenance.orchestrations import OrchestrationHandlerImpl

LEASE = timedelta(seconds=30)
KINDS = [WorkKind.ORCHESTRATION, WorkKind.WAKE_PARKED]


def handlers_of(container: WorkerContainer) -> Mapping[WorkKind, WorkHandlerInterface]:
    """The worker's own handlers."""
    return build_loop(container)._handlers  # pyright: ignore[reportPrivateUsage]


async def drain(
    container: WorkerContainer, handlers: Mapping[WorkKind, WorkHandlerInterface]
) -> list[WorkItem]:
    """Claims every available step and wake-up and runs it with `handlers`,
    settling it as the loop does."""
    ran: list[WorkItem] = []
    while True:
        claimed = await container.managers.work.claim(request(), "default", KINDS, "test", LEASE)
        if claimed is None:
            return ran
        ctx, item = claimed
        await handlers[item.kind].handle(ctx, item)
        await container.managers.work.complete(ctx, item)
        ran.append(item)


async def test_a_record_steps_from_the_queue_until_it_succeeds(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await owner_of(container, "ajax")
    await on_team(container, ctx)
    await drain(container, handlers_of(container))  # the plan's wake-up finds nothing parked
    started = await start_import(container, ctx, 250)
    assert (started.status, started.cursor) == (OrchestrationStatus.RUNNING, 0)
    ran = await drain(container, handlers_of(container))
    assert [item.target_id for item in ran] == [started.id] * 3, "one item a step"
    done = await container.managers.orchestrations.get(ctx, started.id)
    assert (done.status, done.cursor, done.total) == (OrchestrationStatus.SUCCEEDED, 250, 250)
    assert done.finished_at is not None
    # The platform ran the steps; the record is still the person's.
    assert {item.created_by for item in ran} == {ctx.user_id}


async def test_an_import_parks_at_the_plan_and_the_processors_delivery_wakes_it(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    started = await start_import(container, ctx, 50)
    await drain(container, handlers_of(container))
    parked = await container.managers.tasks.imports.get_import(ctx, started.id)
    assert parked.status is OrchestrationStatus.PARKED
    assert parked.park_reason is ParkReason.PLAN_LIMIT
    assert (parked.applied, parked.cursor) == (10, 10)
    # The org pays for Pro: the delivery's apply lands the account and the
    # wake-up in one commit, and the wake-up resumes the import.
    consumer = consumer_of(container)
    paid = await checkout(container, ctx, Plan.PRO, 1)
    assert await consumer.handle(await queued(container, paid)) == "applied"
    ran = await drain(container, handlers_of(container))
    assert ran[0].kind is WorkKind.WAKE_PARKED
    done = await container.managers.tasks.imports.get_import(ctx, started.id)
    assert done.status is OrchestrationStatus.SUCCEEDED
    assert (done.applied, done.cursor, done.total) == (50, 50, 50)
    assert await container.managers.tasks.count_active_tasks(ctx) == 50
    # The platform's delivery woke it; the tasks are still the person's.
    team = TaskFilter(scope=TaskScope.TEAM, user_id=ctx.user_id)
    page = await container.managers.tasks.get_open_tasks(ctx, team, None, 200)
    assert {t.created_by for t in page.items} == {ctx.user_id}


class Flaky:
    """A step that raises until it is told not to: a database that went away."""

    def __init__(self, container: WorkerContainer) -> None:
        self.container = container
        self.failing = True

    async def __call__(self, ctx: TenantContext, record: Orchestration) -> Orchestration:
        if self.failing:
            raise ConnectionResetError("the database went away")
        return await self.container.managers.tasks.imports.step_import(ctx, record)


async def test_a_step_that_errors_is_the_queues_to_retry_and_goes_on_from_its_cursor(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    ctx = await owner_of(container, "ajax")
    await on_team(container, ctx)
    await drain(container, handlers_of(container))  # the plan's wake-up finds nothing parked
    started = await start_import(container, ctx, 250)
    flaky = Flaky(container)
    handler = OrchestrationHandlerImpl(
        container.managers.orchestrations, {OrchestrationKind.TASK_IMPORT: flaky}
    )
    steps = [WorkKind.ORCHESTRATION]
    claimed = await container.managers.work.claim(request(), "default", steps, "test", LEASE)
    assert claimed is not None
    item_ctx, item = claimed
    flaky.failing = False
    await handler.handle(item_ctx, item)  # the first step commits
    await container.managers.work.complete(item_ctx, item)
    flaky.failing = True
    claimed = await container.managers.work.claim(request(), "default", steps, "test", LEASE)
    assert claimed is not None
    item_ctx, item = claimed
    # An attempt that is not the last raises, for the queue to retry.
    with pytest.raises(ConnectionResetError):
        await handler.handle(item_ctx, item)
    halfway = await container.managers.orchestrations.get(ctx, started.id)
    assert (halfway.status, halfway.cursor) == (OrchestrationStatus.RUNNING, 100)
    # The retry: the same item, its next attempt, from the same cursor.
    flaky.failing = False
    await handler.handle(item_ctx, item.model_copy(update={"attempts": item.attempts + 1}))
    await container.managers.work.complete(item_ctx, item)
    assert len(await drain(container, {WorkKind.ORCHESTRATION: handler})) == 1
    done = await container.managers.orchestrations.get(ctx, started.id)
    assert (done.status, done.cursor) == (OrchestrationStatus.SUCCEEDED, 250)
    # Every row made its task once.
    assert done.applied == 250
    assert await container.managers.tasks.count_active_tasks(ctx) == 250


async def test_the_last_attempt_fails_the_record_as_a_defect(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    started = await start_import(container, ctx, 3)
    handler = OrchestrationHandlerImpl(
        container.managers.orchestrations, {OrchestrationKind.TASK_IMPORT: Flaky(container)}
    )
    claimed = await container.managers.work.claim(request(), "default", KINDS, "test", LEASE)
    assert claimed is not None
    item_ctx, item = claimed
    last = item.model_copy(update={"attempts": item.max_attempts})
    await handler.handle(item_ctx, last)
    failed = await container.managers.orchestrations.get(ctx, started.id)
    assert failed.status is OrchestrationStatus.FAILED
    assert failed.fail_reason is FailReason.DEFECT
    assert failed.fail_detail == "ConnectionResetError: the database went away"
    assert failed.cursor == 0, "what it achieved stays; nothing more is done"


async def test_a_step_for_a_record_that_no_longer_runs_does_nothing(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    started = await start_import(container, ctx, 3)
    record = await container.managers.orchestrations.get(ctx, started.id)
    ended = await container.managers.orchestrations.fail(ctx, record, FailReason.DEFECT)
    ran = await drain(container, handlers_of(container))
    assert len(ran) == 1, "the first step's item ran and found nothing to do"
    assert await container.managers.orchestrations.get(ctx, started.id) == ended
    assert await container.managers.tasks.count_active_tasks(ctx) == 0


async def test_the_sweep_opens_the_days_cleanup_and_its_steps_archive_old_done_tasks(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    storage = container.storage.get_tasks_storage()
    for title, days in (("old", 120), ("recent", 30)):
        now = utcnow()
        task = await container.managers.tasks.create_task(
            ctx,
            Task(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                title=title,
            ),
        )
        aged = task.model_copy(
            update={
                "status": TaskStatus.DONE,
                "updated_at": now - timedelta(days=days),
                "version": task.version + 1,
            }
        )
        await storage.update_task(ctx.org_id, aged, task.version, ())
    loop = build_loop(container)
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    # The day's second sweep opens nothing more.
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    page = await container.managers.orchestrations.get_recent(
        ctx, OrchestrationKind.TASK_CLEANUP, 10
    )
    (record,) = page.items
    assert record.input["older_than_days"] == 90
    await drain(container, handlers_of(container))
    done = await container.managers.orchestrations.get(ctx, record.id)
    assert (done.status, done.applied) == (OrchestrationStatus.SUCCEEDED, 1)
    team = TaskFilter(scope=TaskScope.TEAM, user_id=ctx.user_id)
    archived = await container.managers.tasks.get_archived_tasks(ctx, team, None, 10)
    assert [t.title for t in archived.items] == ["old"]


async def test_the_sweep_respaces_a_run_of_long_ranks(tmp_path: Path) -> None:
    """Ninety moves into one gap leave ranks past the bound; one sweep gives
    them short ones, and the list reads as it did."""
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    tasks = container.managers.tasks

    async def add(title: str) -> Task:
        now = utcnow()
        return await tasks.create_task(
            ctx,
            Task(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                title=title,
            ),
        )

    c, a, b = [await add(title) for title in ("c", "a", "b")]
    for index in range(90):
        moved = await tasks.get_task(ctx, (a if index % 2 == 0 else c).id)
        await tasks.move_task(ctx, moved.id, b.id, moved.version)
    team = TaskFilter(scope=TaskScope.TEAM, user_id=ctx.user_id)
    before = (await tasks.get_open_tasks(ctx, team, None, 10)).items
    assert any(needs_respace(t.rank) for t in before)

    await build_loop(container)._sweep_once()  # pyright: ignore[reportPrivateUsage]

    after = (await tasks.get_open_tasks(ctx, team, None, 10)).items
    assert [t.title for t in after] == [t.title for t in before]
    assert not any(needs_respace(t.rank) for t in after)
