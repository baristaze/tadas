import asyncio
import re
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from worker_support import (
    RecordingHandler,
    build_container,
    fast_options,
    make_item,
    request,
    sign_in,
)

from tadas.infra.cache import CacheInterface, CacheScope
from tadas.infra.observability import request_id_var
from tadas.om.base import EMPTY_UUID, new_id, utcnow
from tadas.om.exceptions import LeaseLost
from tadas.om.idempotency.impl.manager import IdempotencyOptions
from tadas.om.opcontext import OpContext, RequestContext
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.types.row import OutboxRow, outbox_row, snapshot
from tadas.om.tasks.types.task import Task
from tadas.om.work import WorkManagerInterface
from tadas.om.work.impl.manager import WorkOptions
from tadas.om.work.types.handler import WorkHandlerInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.loop import LoopOptions, WorkerLoop


class SlowHandler(WorkHandlerInterface):
    def __init__(self, hold: float) -> None:
        self.hold = hold
        self.started: list[UUID] = []
        self.finished: list[UUID] = []
        self.cancelled: list[UUID] = []
        self.request_ids: dict[UUID, str | None] = {}

    async def handle(self, ctx: OpContext, item: WorkItem) -> None:
        self.started.append(item.id)
        self.request_ids[item.id] = request_id_var.get()
        try:
            await asyncio.sleep(self.hold)
        except asyncio.CancelledError:
            self.cancelled.append(item.id)
            raise
        self.finished.append(item.id)


class LeaseLosingWork(WorkManagerInterface):
    """Decorates the real manager: every renewal fails as if another worker held the item."""

    def __init__(self, inner: WorkManagerInterface) -> None:
        self._inner = inner
        self.renewals = 0

    async def enqueue(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        return await self._inner.enqueue(ctx, item)

    async def claim(
        self,
        rctx: RequestContext,
        lane: str,
        kinds: Sequence[WorkKind],
        worker_id: str,
        lease: timedelta,
    ) -> tuple[OpContext, WorkItem] | None:
        return await self._inner.claim(rctx, lane, kinds, worker_id, lease)

    async def complete(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        return await self._inner.complete(ctx, item)

    async def fail(self, ctx: OpContext, item: WorkItem, error: str) -> WorkItem:
        return await self._inner.fail(ctx, item, error)

    async def defer(self, ctx: OpContext, item: WorkItem, delay: timedelta) -> WorkItem:
        return await self._inner.defer(ctx, item, delay)

    async def release(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        return await self._inner.release(ctx, item)

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        self.renewals += 1
        raise LeaseLost("held elsewhere")

    async def requeue_stale(self, ctx: OpContext) -> int:
        return await self._inner.requeue_stale(ctx)

    async def purge_settled(self, ctx: OpContext) -> int:
        return await self._inner.purge_settled(ctx)

    async def maintenance_contexts(self, rctx: RequestContext) -> list[OpContext]:
        return await self._inner.maintenance_contexts(rctx)


class StallingWork(LeaseLosingWork):
    """Decorates the real manager: every renewal hangs, as an unreachable database behaves."""

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        self.renewals += 1
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class FailingWork(LeaseLosingWork):
    """Decorates the real manager: every renewal fails for a reason that says
    nothing about who holds the item, as an engine out of reach behaves."""

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        self.renewals += 1
        raise RuntimeError("engine out of reach")


class FailThenStallWork(LeaseLosingWork):
    """Decorates the real manager: the first renewal fails fast, every later one
    hangs, as an engine that refuses once and then stops answering behaves."""

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        self.renewals += 1
        if self.renewals == 1:
            raise RuntimeError("engine out of reach")
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class FailingReleaseWork(LeaseLosingWork):
    """Decorates the real manager: renewals go through, but every release fails
    for a reason that says nothing about the lease, as a database down at
    shutdown behaves."""

    def __init__(self, inner: WorkManagerInterface) -> None:
        super().__init__(inner)
        self.releases = 0

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        return await self._inner.extend_lease(ctx, item, lease)

    async def release(self, ctx: OpContext, item: WorkItem) -> WorkItem:
        self.releases += 1
        raise RuntimeError("engine out of reach")


class StopOnClaimWork(LeaseLosingWork):
    """Decorates the real manager: renewals go through, and `stop()` lands on
    the claim's way back, in the window between the row being marked CLAIMED
    and the loop creating the task that runs it."""

    def __init__(self, inner: WorkManagerInterface) -> None:
        super().__init__(inner)
        self.stop: Callable[[], None] = lambda: None

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        return await self._inner.extend_lease(ctx, item, lease)

    async def claim(
        self,
        rctx: RequestContext,
        lane: str,
        kinds: Sequence[WorkKind],
        worker_id: str,
        lease: timedelta,
    ) -> tuple[OpContext, WorkItem] | None:
        claimed = await self._inner.claim(rctx, lane, kinds, worker_id, lease)
        if claimed is not None:
            self.stop()
        return claimed


class EnqueueDuringClaimWork(LeaseLosingWork):
    """Decorates the real manager: the claim finds an empty lane, and a producer
    inserts and announces an item while the claim is still on its way back.
    That is the window a Postgres snapshot plus a Valkey publish really open."""

    def __init__(self, inner: WorkManagerInterface, ctx: OpContext, item: WorkItem) -> None:
        super().__init__(inner)
        self._pending: list[WorkItem] = [item]
        self._ctx = ctx

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        return await self._inner.extend_lease(ctx, item, lease)

    async def claim(
        self,
        rctx: RequestContext,
        lane: str,
        kinds: Sequence[WorkKind],
        worker_id: str,
        lease: timedelta,
    ) -> tuple[OpContext, WorkItem] | None:
        claimed = await self._inner.claim(rctx, lane, kinds, worker_id, lease)
        if claimed is None and self._pending:
            await self._inner.enqueue(self._ctx, self._pending.pop())
        return claimed


class MissingLiveness(CacheInterface):
    """A liveness store whose writes never stick, as an unreachable backend behaves."""

    async def get(self, org_id: UUID, key: str) -> bytes | None:
        return None

    async def put(self, org_id: UUID, key: str, value: bytes, ttl: timedelta) -> None:
        return None

    async def invalidate(self, org_id: UUID, key: str) -> None:
        return None

    async def increment(self, org_id: UUID, key: str, ttl: timedelta) -> tuple[int, timedelta]:
        return 0, ttl

    def describe(self) -> str:
        return "cache[worker_liveness]=missing"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


class StallingLiveness(MissingLiveness):
    """A liveness store whose every call hangs, as an unreachable backend behaves
    before its socket times out."""

    async def get(self, org_id: UUID, key: str) -> bytes | None:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def put(self, org_id: UUID, key: str, value: bytes, ttl: timedelta) -> None:
        await asyncio.Event().wait()

    async def invalidate(self, org_id: UUID, key: str) -> None:
        await asyncio.Event().wait()


class RaisingLiveness(MissingLiveness):
    """A liveness store whose every call raises, as a backend that refuses connections behaves."""

    async def get(self, org_id: UUID, key: str) -> bytes | None:
        raise RuntimeError("connection refused")

    async def put(self, org_id: UUID, key: str, value: bytes, ttl: timedelta) -> None:
        raise RuntimeError("connection refused")

    async def invalidate(self, org_id: UUID, key: str) -> None:
        raise RuntimeError("connection refused")


def start_loop(
    container: WorkerContainer,
    handler: WorkHandlerInterface,
    options: LoopOptions,
    *,
    work: WorkManagerInterface | None = None,
    liveness: CacheInterface | None = None,
) -> tuple[WorkerLoop, asyncio.Task[None]]:
    loop = WorkerLoop(
        work=work or container.managers.work,
        outbox=container.managers.outbox,
        purges={
            "tasks": container.managers.tasks.purge_deleted,
            "tenancy": container.managers.tenancy.purge_deleted,
            "idempotency": container.managers.idempotency.purge,
            "work": container.managers.work.purge_settled,
        },
        handlers={WorkKind.NOOP: handler},
        topics=container.infra.get_topics(),
        liveness=liveness or container.infra.get_cache(CacheScope.WORKER_LIVENESS),
        options=options,
    )
    return loop, asyncio.create_task(loop.run())


async def claim_all(outbox: OutboxStorageInterface) -> list[tuple[UUID, OutboxRow]]:
    """What the sweep would claim now, with no grace and no delay after it."""
    zero = timedelta(0)
    return await outbox.claim_pending(100, utcnow(), zero, zero, zero)


async def until(predicate: Callable[[], bool], within: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + within
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


async def test_claims_within_capacity_and_completes(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=0.15)
    loop, task = start_loop(container, handler, fast_options(capacity=1))
    items = [make_item(ctx) for _ in range(3)]
    for item in items:
        await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.started) == 1)
    assert loop.running == 1
    await asyncio.sleep(0.05)
    assert len(handler.started) == 1, "capacity 1 admits one item at a time"
    await until(lambda: len(handler.finished) == 3)
    loop.stop()
    await task
    storage = container.storage.get_work_storage()
    for item in items:
        stored = await storage.read_item(ctx.org_id, item.id)
        assert stored is not None and stored.status is WorkStatus.DONE
    # Each run carried its own request id, the one the claim minted, in the
    # context variable the log filter reads.
    assert len(set(handler.request_ids.values())) == 3
    assert all(rid and rid != str(ctx.request_id) for rid in handler.request_ids.values())


async def test_a_finished_item_wakes_the_claimer(tmp_path: Path) -> None:
    # Every item is queued before the loop starts, so no announcement wakes it:
    # with one slot, the second and third claims happen only because a finished
    # item wakes the claimer, never because the poll interval (an hour) passed.
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    items = [make_item(ctx) for _ in range(3)]
    for item in items:
        await container.managers.work.enqueue(ctx, item)
    handler = SlowHandler(hold=0.05)
    loop, task = start_loop(
        container, handler, fast_options(capacity=1, poll_interval=timedelta(hours=1))
    )
    await until(lambda: len(handler.finished) == 3)
    loop.stop()
    await task


async def test_lease_is_renewed_while_an_item_runs(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=0.7)
    loop, task = start_loop(container, handler, fast_options(lease=timedelta(seconds=0.3)))
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.started) == 1)
    storage = container.storage.get_work_storage()
    first = await storage.read_item(ctx.org_id, item.id)
    assert first is not None and first.lease_expires_at is not None
    await asyncio.sleep(0.35)
    renewed = await storage.read_item(ctx.org_id, item.id)
    assert renewed is not None and renewed.lease_expires_at is not None
    assert renewed.lease_expires_at > first.lease_expires_at
    assert renewed.status is WorkStatus.CLAIMED
    await until(lambda: len(handler.finished) == 1)
    loop.stop()
    await task


async def test_a_lost_lease_cancels_the_task_at_once(tmp_path: Path) -> None:
    # A renewal refused with LeaseLost is definitive: another worker holds the
    # item, so the task is cancelled on the first refusal, a third of the lease
    # in, and not once half the lease has passed.
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=5.0)
    losing = LeaseLosingWork(container.managers.work)
    lease = timedelta(seconds=0.9)
    loop, task = start_loop(container, handler, fast_options(lease=lease), work=losing)
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.started) == 1)
    started = asyncio.get_running_loop().time()
    await until(lambda: len(handler.cancelled) == 1, within=2.0)
    cancelled = asyncio.get_running_loop().time()
    assert losing.renewals == 1, "the first refusal is the answer"
    assert cancelled - started < (lease / 2).total_seconds(), "at once, not after half the lease"
    assert handler.finished == []
    loop.stop()
    await task


async def test_any_other_renewal_failure_cancels_after_half_the_lease(tmp_path: Path) -> None:
    # A renewal that fails for any other reason says nothing about who holds
    # the item, so it is retried; the task is cancelled once half the lease has
    # passed without a renewal, half the lease before it expires.
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=5.0)
    failing = FailingWork(container.managers.work)
    lease = timedelta(seconds=0.9)
    loop, task = start_loop(container, handler, fast_options(lease=lease), work=failing)
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.started) == 1)
    started = asyncio.get_running_loop().time()
    await until(lambda: len(handler.cancelled) == 1, within=2.0)
    cancelled = asyncio.get_running_loop().time()
    assert failing.renewals == 2, (
        "the first failure is retried once; the fence comes before a third"
    )
    assert (lease / 3).total_seconds() < cancelled - started < (lease * 2 / 3).total_seconds()
    assert handler.finished == []
    loop.stop()
    await task


async def test_a_stalled_renewal_counts_as_failed_and_cancels_in_time(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=5.0)
    stalling = StallingWork(container.managers.work)
    lease = timedelta(seconds=1.0)
    loop, task = start_loop(container, handler, fast_options(lease=lease), work=stalling)
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.started) == 1)
    started = asyncio.get_running_loop().time()
    await until(lambda: len(handler.cancelled) == 1, within=2.0)
    cancelled = asyncio.get_running_loop().time()
    assert cancelled - started < lease.total_seconds(), "cancelled before the lease expired"
    assert stalling.renewals >= 1
    assert handler.finished == []
    loop.stop()
    await task


async def test_a_renewal_that_stalls_after_a_failure_still_cancels_in_time(tmp_path: Path) -> None:
    # A fast failure a third of the lease in is retried; the retry stalls. Each
    # attempt is bounded by the time left to the fence at half the lease, so
    # the task is cancelled there, not when the lease has already expired.
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=5.0)
    work = FailThenStallWork(container.managers.work)
    lease = timedelta(seconds=0.9)
    loop, task = start_loop(container, handler, fast_options(lease=lease), work=work)
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.started) == 1)
    started = asyncio.get_running_loop().time()
    await until(lambda: len(handler.cancelled) == 1, within=2.0)
    cancelled = asyncio.get_running_loop().time()
    assert work.renewals == 2, "the fast failure is retried once, the retry stalls"
    assert cancelled - started < (lease * 2 / 3).total_seconds(), "fenced at half the lease"
    assert handler.finished == []
    loop.stop()
    await task


async def test_sweep_requeues_stale_items_per_tenant(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    lost = await container.managers.work.claim(
        request(), "default", [WorkKind.NOOP], "gone-worker", timedelta(seconds=-1)
    )
    assert lost is not None
    handler = RecordingHandler()
    loop, task = start_loop(container, handler, fast_options())
    await until(lambda: [h.id for h in handler.handled] == [item.id])
    loop.stop()
    await task
    stored = await container.storage.get_work_storage().read_item(ctx.org_id, item.id)
    assert stored is not None and stored.status is WorkStatus.DONE
    assert stored.attempts == 2, "the sweep kept the lost attempt; the rerun spent one more"


async def test_a_departed_members_queued_item_still_runs(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    tenancy_storage = container.storage.get_tenancy_storage()
    ann = await tenancy_storage.read_user(ctx.org_id, ctx.user_id)
    assert ann is not None
    now = utcnow()
    await tenancy_storage.write_user(
        ctx.org_id,
        ann.model_copy(update={"deleted_at": now, "deleted_by": ann.id, "updated_at": now}),
    )

    handler = SlowHandler(hold=0)
    loop, task = start_loop(container, handler, fast_options())
    await until(lambda: handler.finished == [item.id])
    loop.stop()
    await task
    stored = await container.storage.get_work_storage().read_item(ctx.org_id, item.id)
    assert stored is not None and stored.status is WorkStatus.DONE
    assert stored.created_by == ctx.user_id, "the attribution survived the hop"


async def test_sweep_reaches_a_tenant_whose_members_have_all_left(tmp_path: Path) -> None:
    # The stale item sits on a lane this loop never claims from, so what moves
    # it is the sweep alone; the tenant's only member is gone by then.
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    item = make_item(ctx).model_copy(update={"lane": "other"})
    await container.managers.work.enqueue(ctx, item)
    lost = await container.managers.work.claim(
        request(), "other", [WorkKind.NOOP], "gone-worker", timedelta(seconds=-1)
    )
    assert lost is not None
    tenancy_storage = container.storage.get_tenancy_storage()
    ann = await tenancy_storage.read_user(ctx.org_id, ctx.user_id)
    assert ann is not None
    now = utcnow()
    await tenancy_storage.write_user(
        ctx.org_id,
        ann.model_copy(update={"deleted_at": now, "deleted_by": ann.id, "updated_at": now}),
    )

    loop, task = start_loop(container, RecordingHandler(), fast_options())
    await until(lambda: loop.sweeps >= 1)
    loop.stop()
    await task
    stored = await container.storage.get_work_storage().read_item(ctx.org_id, item.id)
    assert stored is not None and stored.status is WorkStatus.QUEUED
    assert stored.claimed_by is None and stored.updated_by == EMPTY_UUID


async def test_sweep_relays_the_outbox_and_purges_done_rows(tmp_path: Path) -> None:
    # A row a crash left behind: written with its core row, never relayed.
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    now = utcnow()
    task = Task(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        title="left behind",
    )
    row = outbox_row(ctx, "tasks.task.created", task.id, snapshot(task)).model_copy(
        update={"created_at": now - timedelta(minutes=1)}  # older than the relay's grace
    )
    await container.storage.get_tasks_storage().create_task(ctx.org_id, task, row)
    outbox = container.storage.get_outbox_storage()
    assert [r.id for _, r in await claim_all(outbox)] == [row.id]
    loop, task_ = start_loop(
        container, RecordingHandler(), fast_options(outbox_retention=timedelta(0))
    )
    await until(lambda: loop.sweeps >= 2)
    loop.stop()
    await task_
    assert await claim_all(outbox) == [], "the sweep relayed the row"
    events = await container.managers.events.get_events(ctx, after_seq=0, limit=10)
    assert [(e.id, e.kind, e.target_id) for e in events] == [(row.id, row.kind, task.id)]
    # With no retention the second sweep purged the done row: nothing pending,
    # nothing done, and the relay of a purged row is never asked for.
    assert await outbox.purge_done(utcnow()) == 0


async def test_a_lost_lease_is_never_written_over(tmp_path: Path) -> None:
    # The second fence: the handler finishes before any renewal runs (the
    # lease is long), and the completion itself is refused because the claim
    # is no longer this worker's.
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=0.3)
    loop, task = start_loop(
        container,
        handler,
        fast_options(sweep_interval=timedelta(hours=1), lease=timedelta(seconds=3)),
    )
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.started) == 1)
    storage = container.storage.get_work_storage()
    held = await storage.read_item(ctx.org_id, item.id)
    assert held is not None and held.status is WorkStatus.CLAIMED
    # The sweep deems the lease expired (its clock runs an hour ahead) and
    # hands the item back before this worker's handler finishes.
    requeued = await storage.requeue_stale(
        ctx.org_id, utcnow() + timedelta(hours=1), timedelta(0), new_id()
    )
    assert [r.id for r in requeued] == [item.id]
    await until(lambda: len(handler.finished) == 1)
    await until(lambda: loop.running == 0)
    stored = await storage.read_item(ctx.org_id, item.id)
    assert stored == requeued[0], "complete() saw the lease was lost and wrote nothing"
    loop.stop()
    await task


async def test_heartbeat_failure_pauses_claiming(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = RecordingHandler()
    loop, task = start_loop(container, handler, fast_options(), liveness=MissingLiveness())
    await until(lambda: loop.paused)
    await container.managers.work.enqueue(ctx, make_item(ctx))
    await asyncio.sleep(0.2)
    assert handler.handled == [], "a worker whose heartbeats fail claims nothing new"
    loop.stop()
    await task


async def test_stop_drains_first_and_goes_offline_last(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=5.0)
    loop, task = start_loop(container, handler, fast_options())
    liveness = container.infra.get_cache(CacheScope.WORKER_LIVENESS)
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.started) == 1)
    await until(lambda: loop.online)
    assert await liveness.get(EMPTY_UUID, "worker:maintenance-test") == b"online"
    loop.stop()
    await task
    assert handler.cancelled == [item.id]
    stored = await container.storage.get_work_storage().read_item(ctx.org_id, item.id)
    assert stored is not None
    assert stored.status is WorkStatus.QUEUED
    assert stored.claimed_by is None
    assert stored.attempts == 0
    assert stored.last_error == "returned: worker stopping"
    assert await liveness.get(EMPTY_UUID, "worker:maintenance-test") is None
    assert loop.sweeps >= 1


async def test_stop_goes_offline_even_when_a_release_fails(tmp_path: Path) -> None:
    # The database is down at shutdown: returning the item fails with an error
    # that says nothing about the lease. The drain still awaits every item,
    # the heartbeat and the sweep still end, the worker still goes offline,
    # and `run()` still returns.
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=5.0)
    work = FailingReleaseWork(container.managers.work)
    loop, task = start_loop(container, handler, fast_options(capacity=2), work=work)
    liveness = container.infra.get_cache(CacheScope.WORKER_LIVENESS)
    items = [make_item(ctx), make_item(ctx)]
    for item in items:
        await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.started) == 2)
    await until(lambda: loop.online)
    loop.stop()
    await asyncio.wait_for(task, 2.0)
    await asyncio.wait_for(loop.wait_drained(), 1.0)
    assert sorted(handler.cancelled) == sorted(item.id for item in items)
    assert work.releases == 2, "every item was awaited, the first failure stopped nothing"
    assert loop.running == 0
    assert await liveness.get(EMPTY_UUID, "worker:maintenance-test") is None
    assert loop.online is False
    names = {t.get_name() for t in asyncio.all_tasks()}
    assert not names & {"heartbeat", "sweep"}, "the timers were cancelled"


async def test_a_stalled_liveness_store_counts_as_a_failed_heartbeat(tmp_path: Path) -> None:
    # Each heartbeat is bounded by its interval, so a store that never answers
    # pauses claiming the way one whose writes never stick does, and the stop
    # still returns although marking offline hangs too.
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = RecordingHandler()
    loop, task = start_loop(container, handler, fast_options(), liveness=StallingLiveness())
    await until(lambda: loop.paused)
    await container.managers.work.enqueue(ctx, make_item(ctx))
    await asyncio.sleep(0.2)
    assert handler.handled == [], "a worker whose heartbeats stall claims nothing new"
    loop.stop()
    await asyncio.wait_for(task, 2.0)
    await asyncio.wait_for(loop.wait_drained(), 1.0)


async def test_a_raising_liveness_store_counts_as_a_failed_heartbeat(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    await sign_in(container)
    loop, task = start_loop(
        container, RecordingHandler(), fast_options(), liveness=RaisingLiveness()
    )
    await until(lambda: loop.paused)
    loop.stop()
    await asyncio.wait_for(task, 2.0)
    await asyncio.wait_for(loop.wait_drained(), 1.0)
    assert loop.online is False


def test_outbox_retention_outlives_the_database_backup_retention() -> None:
    """A role restored to an earlier point than its siblings is reconciled by
    relaying the outbox again, so done rows must survive as long as a backup can
    be old. The bound is the database module's `backup_retention_days`."""
    variables = (
        Path(__file__).resolve().parents[3] / "deployment/terraform/modules/database/variables.tf"
    ).read_text()
    block = variables.split('variable "backup_retention_days"', 1)[1].split("}", 1)[0]
    match = re.search(r"default\s*=\s*(\d+)", block)
    assert match is not None
    backup_days = int(match.group(1))
    assert LoopOptions(worker_id="w").outbox_retention > timedelta(days=backup_days)


async def test_sweep_purges_settled_work_items_and_finished_idempotency_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    monkeypatch.setattr(container.managers.work, "_options", WorkOptions(retention=timedelta(0)))
    monkeypatch.setattr(
        container.managers.idempotency, "_options", IdempotencyOptions(retention=timedelta(0))
    )
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    begun = await container.managers.idempotency.begin(ctx, "k", "d", new_id())
    assert begun.attempt_id is not None
    await container.managers.idempotency.finish(ctx, "k", begun.attempt_id, 201, "{}")
    handler = RecordingHandler()
    loop, task = start_loop(container, handler, fast_options())
    await until(lambda: [h.id for h in handler.handled] == [item.id])
    sweeps = loop.sweeps
    await until(lambda: loop.sweeps >= sweeps + 2)
    loop.stop()
    await task
    assert await container.storage.get_work_storage().read_item(ctx.org_id, item.id) is None
    idempotency = container.storage.get_idempotency_storage()
    assert await idempotency.read_record(ctx.org_id, ctx.user_id, "k") is None


async def test_stop_during_a_claim_still_returns_the_item(tmp_path: Path) -> None:
    """`stop()` lands while the claim is on its way back: the loop exits before
    the task it created has taken a step. Cancelling a task that never ran
    raises at its first instruction, so the handler's `except CancelledError`
    never returns the item, and it would sit CLAIMED by a worker that is gone
    until the lease expired and the sweep requeued it as a stale lease."""
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=5.0)
    work = StopOnClaimWork(container.managers.work)
    loop, task = start_loop(container, handler, fast_options(), work=work)
    work.stop = loop.stop
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    await asyncio.wait_for(task, 3.0)
    stored = await container.storage.get_work_storage().read_item(ctx.org_id, item.id)
    assert stored is not None
    assert stored.status is WorkStatus.QUEUED, "the item was left claimed by a stopped worker"
    assert stored.claimed_by is None
    assert stored.last_error == "returned: worker stopping"
    assert loop.running == 0


async def test_an_announcement_during_a_claim_is_not_lost(tmp_path: Path) -> None:
    """The claim snapshots an empty lane, a producer inserts and announces, and
    the claim then returns nothing. The wake the announcement set belongs to
    the item the claim never saw: clearing it after the claim threw it away
    and the item waited out the whole poll interval, an hour here."""
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=0.05)
    item = make_item(ctx)
    work = EnqueueDuringClaimWork(container.managers.work, ctx, item)
    loop, task = start_loop(
        container, handler, fast_options(poll_interval=timedelta(hours=1)), work=work
    )
    await until(lambda: handler.started == [item.id], within=2.0)
    loop.stop()
    await asyncio.wait_for(task, 3.0)
