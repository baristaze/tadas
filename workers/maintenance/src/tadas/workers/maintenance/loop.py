"""The worker loop: wake on WORK_AVAILABLE with a short poll fallback, claim
while a slot is free, run each item as a task that renews its lease and
cancels itself when renewal keeps failing, heartbeat liveness, sweep on a
timer, and drain first on stop."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Mapping
from datetime import timedelta

from tadas.infra.cache import CacheInterface
from tadas.infra.observability import OUTCOMES
from tadas.infra.topics import TopicPayload, Topics, TopicsInterface, WorkAvailablePayload
from tadas.om.base import EMPTY_UUID, Platform
from tadas.om.exceptions import LeaseLost, NotFound
from tadas.om.opcontext import OpContext
from tadas.om.work import WorkManagerInterface
from tadas.om.work.types.handler import WorkHandlerInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind

log = logging.getLogger(__name__)


class LoopOptions(Platform):
    worker_id: str
    queue: str = "default"
    capacity: int = 4
    lease: timedelta = timedelta(seconds=60)
    heartbeat_interval: timedelta = timedelta(seconds=10)
    heartbeat_failure_limit: int = 3
    sweep_interval: timedelta = timedelta(seconds=30)
    poll_interval: timedelta = timedelta(seconds=5)


class WorkerLoop:
    def __init__(
        self,
        *,
        work: WorkManagerInterface,
        handlers: Mapping[WorkKind, WorkHandlerInterface],
        topics: TopicsInterface,
        liveness: CacheInterface,
        options: LoopOptions,
    ) -> None:
        self._work = work
        self._handlers = handlers
        self._topics = topics
        self._liveness = liveness
        self._options = options
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._drained = asyncio.Event()
        self._running: dict[asyncio.Task[None], tuple[OpContext, WorkItem]] = {}
        self._heartbeat_failures = 0
        self.paused = False
        self.online = False
        self.sweeps = 0

    @property
    def kinds(self) -> list[WorkKind]:
        return list(self._handlers)

    @property
    def running(self) -> int:
        return len(self._running)

    async def run(self) -> None:
        """Runs until `stop()`; returns once every item is back in the queue and the
        worker is marked offline."""
        unsubscribe = self._topics.subscribe(
            Topics.WORK_AVAILABLE, f"worker:{self._options.worker_id}", self._on_work_available
        )
        heartbeat = asyncio.create_task(self._heartbeat_forever(), name="heartbeat")
        sweep = asyncio.create_task(self._sweep_forever(), name="sweep")
        try:
            await self._claim_until_stopped()
        finally:
            unsubscribe()
            await self._drain()
            heartbeat.cancel()
            sweep.cancel()
            for task in (heartbeat, sweep):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await self._mark_offline()
            self._drained.set()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()

    async def wait_drained(self) -> None:
        await self._drained.wait()

    # Claiming.

    async def _on_work_available(self, payload: TopicPayload) -> None:
        if isinstance(payload, WorkAvailablePayload) and payload.queue == self._options.queue:
            self._wake.set()

    async def _claim_until_stopped(self) -> None:
        while not self._stopping.is_set():
            if not self.paused and len(self._running) < self._options.capacity:
                claimed = await self._try_claim()
                if claimed:
                    continue
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self._options.poll_interval.total_seconds()
                )

    async def _try_claim(self) -> bool:
        try:
            claimed = await self._work.claim(
                self._options.queue, self.kinds, self._options.worker_id, self._options.lease
            )
        except Exception:
            log.exception("claim failed")
            OUTCOMES.labels(subsystem="worker", outcome="claim_error").inc()
            return False
        if claimed is None:
            return False
        ctx, item = claimed
        task = asyncio.create_task(self._run_item(ctx, item), name=f"work-{item.id}")
        self._running[task] = (ctx, item)
        task.add_done_callback(lambda done: self._running.pop(done, None))
        return True

    # Running one item.

    async def _run_item(self, ctx: OpContext, item: WorkItem) -> None:
        handler = self._handlers.get(item.kind)
        if handler is None:
            await self._settle(item, self._work.release(ctx, item), "released")
            return
        renewal = asyncio.create_task(
            self._renew_lease(ctx, item, asyncio.current_task()), name=f"lease-{item.id}"
        )
        try:
            await handler.handle(ctx, item)
        except asyncio.CancelledError:
            if self._stopping.is_set():
                note = item.model_copy(update={"last_error": "returned: worker stopping"})
                await self._settle(item, self._work.release(ctx, note), "returned")
            else:
                log.warning("lease lost on %s; task cancelled before the lease expired", item.id)
                OUTCOMES.labels(subsystem="worker", outcome="lease_lost").inc()
        except Exception as error:
            log.exception("handler failed on %s", item.id)
            failure = self._work.fail(ctx, item, f"{type(error).__name__}: {error}"[:500])
            await self._settle(item, failure, "failed")
        else:
            await self._settle(item, self._work.complete(ctx, item), "done")
        finally:
            renewal.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renewal

    @staticmethod
    async def _settle(item: WorkItem, transition: Awaitable[WorkItem], outcome: str) -> None:
        """Writes the item's transition; a lease that was lost in the meantime is
        logged and counted, never written over."""
        try:
            await transition
        except (LeaseLost, NotFound) as error:
            log.warning("%s was not settled as %s: %s", item.id, outcome, error)
            OUTCOMES.labels(subsystem="worker", outcome="lease_lost").inc()
            return
        OUTCOMES.labels(subsystem="worker", outcome=outcome).inc()

    async def _renew_lease(
        self, ctx: OpContext, item: WorkItem, owner: asyncio.Task[None] | None
    ) -> None:
        """Renews every third of the lease, each renewal bounded by that interval so
        a stalled one counts as failed. Once half the lease has passed since the
        last renewal that succeeded, cancels the owner before the lease expires so
        two workers never advance the same record."""
        lease = self._options.lease
        interval = lease / 3
        clock = asyncio.get_running_loop().time
        renewed_at = clock()
        while True:
            await asyncio.sleep(interval.total_seconds())
            try:
                await asyncio.wait_for(
                    self._work.extend_lease(ctx, item, lease), timeout=interval.total_seconds()
                )
                renewed_at = clock()
            except Exception as error:
                log.warning("lease renewal failed on %s: %r", item.id, error)
                if clock() - renewed_at >= (lease / 2).total_seconds():
                    if owner is not None:
                        owner.cancel()
                    return

    # Liveness.

    async def _heartbeat_forever(self) -> None:
        while True:
            await self._heartbeat_once()
            await asyncio.sleep(self._options.heartbeat_interval.total_seconds())

    async def _heartbeat_once(self) -> None:
        key = f"worker:{self._options.worker_id}"
        ttl = self._options.heartbeat_interval * 3
        await self._liveness.put(EMPTY_UUID, key, b"online", ttl)
        if await self._liveness.get(EMPTY_UUID, key) is None:
            self._heartbeat_failures += 1
            if (
                self._heartbeat_failures >= self._options.heartbeat_failure_limit
                and not self.paused
            ):
                log.error("heartbeat failed %d times; claiming paused", self._heartbeat_failures)
                self.paused = True
            return
        self.online = True
        if self.paused:
            log.info("heartbeat recovered; claiming resumed")
        self._heartbeat_failures = 0
        self.paused = False

    async def _mark_offline(self) -> None:
        await self._liveness.invalidate(EMPTY_UUID, f"worker:{self._options.worker_id}")
        self.online = False

    # Maintenance.

    async def _sweep_forever(self) -> None:
        while True:
            await self._sweep_once()
            await asyncio.sleep(self._options.sweep_interval.total_seconds())

    async def _sweep_once(self) -> None:
        """One service context per live tenant, then every step under each of them.
        Every step is idempotent and wrapped, so a failing tenant never stops the rest."""
        try:
            contexts = await self._work.maintenance_contexts()
        except Exception:
            log.exception("sweep: maintenance_contexts failed")
            contexts = []
        for ctx in contexts:
            try:
                await self._work.requeue_stale(ctx)
            except Exception:
                log.exception("sweep: requeue_stale failed for tenant %s", ctx.org_id)
        self.sweeps += 1

    # Shutdown.

    async def _drain(self) -> None:
        tasks = list(self._running)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
