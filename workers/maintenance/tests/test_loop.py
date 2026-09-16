import asyncio
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from worker_support import build_container, fast_options, make_item, sign_in

from tadas.infra.cache import CacheInterface, CacheScope
from tadas.om.base import EMPTY_UUID
from tadas.om.exceptions import LeaseLost
from tadas.om.opcontext import OpContext
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

    async def handle(self, ctx: OpContext, item: WorkItem) -> None:
        self.started.append(item.id)
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
        self, queue: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[OpContext, WorkItem] | None:
        return await self._inner.claim(queue, kinds, worker_id, lease)

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

    async def requeue_stale(self) -> int:
        return await self._inner.requeue_stale()

    async def maintenance_contexts(self) -> list[OpContext]:
        return await self._inner.maintenance_contexts()


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
