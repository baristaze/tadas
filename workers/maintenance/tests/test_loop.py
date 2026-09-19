import asyncio
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from worker_support import build_container, fast_options, make_item, request, sign_in

from tadas.infra.cache import CacheInterface, CacheScope
from tadas.infra.observability import request_id_var
from tadas.om.base import EMPTY_UUID, new_id, utcnow
from tadas.om.exceptions import LeaseLost
from tadas.om.opcontext import OpContext, RequestContext
from tadas.om.outbox.types.row import outbox_row, snapshot
from tadas.om.tasks.types.task import Task
from tadas.om.work import WorkManagerInterface
from tadas.om.work.types.handler import WorkHandlerInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.handler import NoopHandlerImpl
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

    async def maintenance_contexts(self, rctx: RequestContext) -> list[OpContext]:
        return await self._inner.maintenance_contexts(rctx)


class StallingWork(LeaseLosingWork):
    """Decorates the real manager: every renewal hangs, as an unreachable database behaves."""

    async def extend_lease(self, ctx: OpContext, item: WorkItem, lease: timedelta) -> WorkItem:
        self.renewals += 1
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


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
        },
        handlers={WorkKind.NOOP: handler},
        topics=container.infra.get_topics(),
        liveness=liveness or container.infra.get_cache(CacheScope.WORKER_LIVENESS),
        options=options,
    )
    return loop, asyncio.create_task(loop.run())


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


async def test_lease_loss_cancels_the_task_before_the_lease_expires(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=5.0)
    losing = LeaseLosingWork(container.managers.work)
    loop, task = start_loop(
        container, handler, fast_options(lease=timedelta(seconds=0.6)), work=losing
    )
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.cancelled) == 1, within=2.0)
    assert losing.renewals >= 1
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


async def test_sweep_requeues_stale_items_per_tenant(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    lost = await container.managers.work.claim(
        request(), "default", [WorkKind.NOOP], "gone-worker", timedelta(seconds=-1)
    )
    assert lost is not None
    handler = NoopHandlerImpl()
    loop, task = start_loop(container, handler, fast_options())
    await until(lambda: [h.id for h in handler.handled] == [item.id])
    loop.stop()
    await task
    stored = await container.storage.get_work_storage().read_item(ctx.org_id, item.id)
    assert stored is not None and stored.status is WorkStatus.DONE
    assert stored.attempts == 2, "the sweep kept the lost attempt; the rerun spent one more"


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
    row = outbox_row(ctx, "tasks.task.created", task.id, snapshot(task))
    await container.storage.get_tasks_storage().write_task(ctx.org_id, task, row)
    outbox = container.storage.get_outbox_storage()
    assert [r.id for _, r in await outbox.read_pending(10)] == [row.id]
    loop, task_ = start_loop(
        container, NoopHandlerImpl(), fast_options(outbox_retention=timedelta(0))
    )
    await until(lambda: loop.sweeps >= 2)
    loop.stop()
    await task_
    assert await outbox.read_pending(10) == [], "the sweep relayed the row"
    events = await container.managers.events.get_events(ctx, after_seq=0, limit=10)
    assert [(e.id, e.kind, e.target_id) for e in events] == [(row.id, row.kind, task.id)]
    # With no retention the second sweep purged the done row: nothing pending,
    # nothing done, and the relay of a purged row is never asked for.
    assert await outbox.purge_done(utcnow()) == 0


async def test_a_lost_lease_is_never_written_over(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = SlowHandler(hold=0.3)
    loop, task = start_loop(container, handler, fast_options(sweep_interval=timedelta(hours=1)))
    item = make_item(ctx)
    await container.managers.work.enqueue(ctx, item)
    await until(lambda: len(handler.started) == 1)
    storage = container.storage.get_work_storage()
    held = await storage.read_item(ctx.org_id, item.id)
    assert held is not None and held.status is WorkStatus.CLAIMED
    taken = held.model_copy(update={"claimed_by": "other-worker"})
    await storage.write_item(ctx.org_id, taken)
    await until(lambda: len(handler.finished) == 1)
    await until(lambda: loop.running == 0)
    stored = await storage.read_item(ctx.org_id, item.id)
    assert stored == taken, "complete() saw the lease was lost and wrote nothing"
    loop.stop()
    await task


async def test_heartbeat_failure_pauses_claiming(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    handler = NoopHandlerImpl()
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
