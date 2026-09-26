"""The worker loop: wake on WORK_AVAILABLE with a short poll fallback, claim
on the lane while a slot is free, run each item as a task that names the
request that caused the work, raises a span linked to that request's trace,
renews its lease and cancels itself when the lease is lost or renewal keeps
failing, beat liveness in memory and publish it to the cache as best
effort, sweep on a timer (the expired leases and the outbox relay across
tenants, then every namespace's purge and the standing chores per tenant,
then the purges of done outbox rows and settled work items, within a time
budget), and drain first on stop."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from tadas.infra.cache import CacheInterface
from tadas.infra.observability import (
    OUTCOMES,
    SWEEP_SECONDS,
    caused_by_request_id_var,
    links_to,
    request_id_var,
)
from tadas.infra.topics import TopicPayload, Topics, TopicsInterface, WorkAvailablePayload
from tadas.om.base import EMPTY_UUID, Platform, new_id
from tadas.om.exceptions import LeaseLost, NotFound
from tadas.om.opcontext import AppContext, AppType, OpContext, RequestContext
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.work import WorkManagerInterface
from tadas.om.work.types.handler import WorkHandlerInterface, WorkParked, WorkRefused
from tadas.om.work.types.work_item import WorkItem, WorkKind

log = logging.getLogger(__name__)

tracer = trace.get_tracer("tadas.workers.maintenance")
"""Resolved against whatever provider boot configured; the no-op one otherwise."""

REQUEST_ID_ATTRIBUTE = "tadas.request_id"
CAUSED_BY_ATTRIBUTE = "tadas.caused_by_request_id"
WORK_ITEM_ATTRIBUTE = "tadas.work_item_id"

PurgeStep = Callable[[OpContext], Awaitable[int]]
"""A manager's `purge_deleted(ctx)`: the one hard delete, per tenant, after
retention, a batch per statement; it returns how many rows went, and a count
of a whole batch or more says there may be more."""

ChoreStep = Callable[[OpContext], Awaitable[object]]
"""A standing chore per tenant that is not a purge: opening the next period
of a record kept per period (`TasksManagerInterface.open_cleanup`)."""


class LoopOptions(Platform):
    worker_id: str
    lane: str = "default"
    capacity: int = 4
    lease: timedelta = timedelta(seconds=60)
    heartbeat_interval: timedelta = timedelta(seconds=10)
    sweep_interval: timedelta = timedelta(seconds=30)
    poll_interval: timedelta = timedelta(seconds=5)
    # Pending rows one relay call claims, and expired leases one requeue
    # statement moves, across tenants. Each is called again while its batch
    # comes back full and the budget lasts.
    outbox_batch: int = 100
    requeue_batch: int = 100
    # Done rows are purged after this. It outlives the database backup retention
    # (`backup_retention_days` in the database module), so a role restored to an
    # earlier point than its siblings is reconciled by relaying the outbox again.
    outbox_retention: timedelta = timedelta(days=8)
    # Rows one purge statement deletes at most: the managers' batch, which the
    # loop reads to know a full one. A purge that returns this many or more is
    # called again while the budget lasts; one that returns fewer is drained.
    purge_batch: int = 1000
    # A pass takes no new tenant past this, and the next pass resumes at the
    # tenant it stopped at, so a pass stays shorter than the interval.
    sweep_budget: timedelta = timedelta(seconds=20)


class WorkerLoop:
    def __init__(
        self,
        *,
        work: WorkManagerInterface,
        outbox: OutboxRelayInterface,
        purges: Mapping[str, PurgeStep],
        handlers: Mapping[WorkKind, WorkHandlerInterface],
        chores: Mapping[str, ChoreStep] | None = None,
        topics: TopicsInterface,
        liveness: CacheInterface,
        options: LoopOptions,
    ) -> None:
        self._work = work
        self._outbox = outbox
        self._purges = purges
        self._chores = dict(chores or {})
        self._handlers = handlers
        self._topics = topics
        self._liveness = liveness
        self._options = options
        self._app = AppContext(type=AppType.WORKER, version=f"worker@{options.worker_id}")
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._drained = asyncio.Event()
        self._running: dict[asyncio.Task[None], tuple[OpContext, WorkItem]] = {}
        self._last_beat: float | None = None
        self.online = False
        self.sweeps = 0
        # Where the next pass starts: the tenant the last one stopped at, or
        # None when it reached the end.
        self._resume_at: UUID | None = None

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
            # Every step of the shutdown runs whatever the step before it met, and
            # `wait_drained()` returns whatever happened: a step that fails is logged.
            unsubscribe()
            try:
                await self._drain()
                heartbeat.cancel()
                sweep.cancel()
                for timer, ended in zip(
                    (heartbeat, sweep),
                    await asyncio.gather(heartbeat, sweep, return_exceptions=True),
                    strict=True,
                ):
                    if isinstance(ended, Exception):
                        log.error("%s ended with %r", timer.get_name(), ended)
                await self._mark_offline()
            finally:
                self._drained.set()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()

    async def wait_drained(self) -> None:
        await self._drained.wait()

    # Claiming.

    async def _on_work_available(self, payload: TopicPayload) -> None:
        if isinstance(payload, WorkAvailablePayload) and payload.lane == self._options.lane:
            self._wake.set()

    async def _claim_until_stopped(self) -> None:
        # The wake is cleared before the claim, never after it: a producer that
        # inserts and publishes while the claim is still finishing sets the
        # event, and clearing it afterwards would throw that wake away and
        # leave a runnable item waiting out the whole poll interval.
        while not self._stopping.is_set():
            self._wake.clear()
            if len(self._running) < self._options.capacity:
                claimed = await self._try_claim()
                if claimed:
                    continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self._options.poll_interval.total_seconds()
                )

    def _request(self) -> RequestContext:
        """The request stage the worker mints at its edge: one per claim and one per
        sweep pass, the way the gateway mints one per request."""
        return RequestContext(request_id=new_id(), app=self._app)

    async def _try_claim(self) -> bool:
        try:
            claimed = await self._work.claim(
                self._request(),
                self._options.lane,
                self.kinds,
                self._options.worker_id,
                self._options.lease,
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
        task.add_done_callback(self._on_item_done)
        return True

    def _on_item_done(self, task: asyncio.Task[None]) -> None:
        """A finished item frees a slot, so the claimer is woken: the poll interval
        bounds how long a queue waits for a worker, not how fast one drains it."""
        self._running.pop(task, None)
        if not task.cancelled() and (error := task.exception()) is not None:
            log.error("work task %s ended with %r", task.get_name(), error)
        self._wake.set()

    # Running one item.

    async def _run_item(self, ctx: OpContext, item: WorkItem) -> None:
        # The claim refined the request stage minted for it; every log line of
        # the run carries its request id, the way the API's middleware does,
        # and the request that caused the work beside it.
        token = request_id_var.set(str(ctx.request_id))
        cause = caused_by_request_id_var.set(
            str(ctx.caused_by_request_id) if ctx.caused_by_request_id is not None else None
        )
        try:
            # The run's span, linked to the trace of the request that filled
            # the queue and not a child of it: the item waited in a durable
            # queue, which holds it well past the end of that request, so the
            # causal edge joins two traces instead of stretching one over
            # both. An item with no trace context on it starts a trace here.
            with tracer.start_as_current_span(
                f"work {item.kind.value}",
                kind=SpanKind.CONSUMER,
                links=links_to(item.traceparent),
                attributes=self._span_attributes(ctx, item),
            ):
                await self._handle(ctx, item)
        finally:
            caused_by_request_id_var.reset(cause)
            request_id_var.reset(token)

    @staticmethod
    def _span_attributes(ctx: OpContext, item: WorkItem) -> dict[str, str]:
        """The run's two requests and the item it advances. The cause is there
        only where the handoff named one; an attribute with nothing in it says
        less than no attribute."""
        attributes = {
            REQUEST_ID_ATTRIBUTE: str(ctx.request_id),
            WORK_ITEM_ATTRIBUTE: str(item.id),
        }
        if ctx.caused_by_request_id is not None:
            attributes[CAUSED_BY_ATTRIBUTE] = str(ctx.caused_by_request_id)
        return attributes

    async def _handle(self, ctx: OpContext, item: WorkItem) -> None:
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
        except WorkParked as parked:
            # A guard, not a failure: back to the queue for the time the
            # handler named, with its reason as the note, no attempt spent.
            log.info("parked %s for %s: %s", item.id, parked.resume_after, parked.reason)
            note = item.model_copy(update={"last_error": f"parked: {parked.reason}"})
            await self._settle(item, self._work.defer(ctx, note, parked.resume_after), "parked")
        except WorkRefused as refused:
            # No retry changes the answer: failed at once, a dead letter.
            log.warning("refused %s: %s", item.id, refused.reason)
            reason = f"refused: {refused.reason}"[:500]
            await self._settle(item, self._work.fail_for_good(ctx, item, reason), "refused")
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
        except asyncio.CancelledError:
            # The fence cancelled the item while its transition was in flight.
            # Whether the write landed is the database's answer and not ours,
            # and the sweep requeues the item if it did not; the run is said
            # here either way, since the cancellation stops every line after it.
            log.warning("%s was cancelled while it was settled as %s", item.id, outcome)
            OUTCOMES.labels(subsystem="worker", outcome="lease_lost").inc()
            raise
        OUTCOMES.labels(subsystem="worker", outcome=outcome).inc()

    async def _renew_lease(
        self, ctx: OpContext, item: WorkItem, owner: asyncio.Task[None] | None
    ) -> None:
        """Renews a third of the lease after the last renewal that succeeded. The
        fence is half the lease after it: every attempt is bounded by the time
        left to the fence, a failed one is retried halfway between the first
        attempt and the fence, and at the fence the owner is cancelled, half
        the lease before it expires, so two workers never advance the same
        record. A renewal refused with LeaseLost is definitive: another worker
        holds the item now, so the owner is cancelled at once."""
        lease = self._options.lease
        interval = (lease / 3).total_seconds()
        fence = (lease / 2).total_seconds()
        retry = (fence - interval) / 2
        clock = asyncio.get_running_loop().time
        renewed_at = clock()
        pause = interval
        while True:
            await asyncio.sleep(pause)
            left = renewed_at + fence - clock()
            if left <= 0:
                if owner is not None:
                    owner.cancel()
                return
            try:
                await asyncio.wait_for(self._work.extend_lease(ctx, item, lease), timeout=left)
                renewed_at = clock()
                pause = interval
            except LeaseLost as error:
                log.warning("lease on %s is held elsewhere: %s", item.id, error)
                if owner is not None:
                    owner.cancel()
                return
            except Exception as error:
                log.warning("lease renewal failed on %s: %r", item.id, error)
                pause = min(retry, max(renewed_at + fence - clock(), 0))

    # Liveness.

    def alive(self) -> bool:
        """True while the heartbeat has beaten within three intervals. The beat is
        the loop's own, held in memory: it stops when the event loop blocks or
        the heartbeat task dies, and a cache that is down does not stop it. The
        queue and its leases live in the database, so a cache outage is no
        reason to stop claiming or to be restarted."""
        if self._last_beat is None:
            return False
        since = asyncio.get_running_loop().time() - self._last_beat
        return since < (self._options.heartbeat_interval * 3).total_seconds()

    async def _heartbeat_forever(self) -> None:
        while True:
            await self._heartbeat_once()
            await asyncio.sleep(self._options.heartbeat_interval.total_seconds())

    async def _heartbeat_once(self) -> None:
        """One beat: recorded in memory first, then published to the cache as best
        effort, bounded by the interval, so other replicas and operators can see
        the worker. A store that stalls, raises, or reads back empty leaves the
        worker unpublished and nothing else."""
        self._last_beat = asyncio.get_running_loop().time()
        key = f"worker:{self._options.worker_id}"
        ttl = self._options.heartbeat_interval * 3
        try:
            async with asyncio.timeout(self._options.heartbeat_interval.total_seconds()):
                await self._liveness.put(EMPTY_UUID, key, b"online", ttl)
                stored = await self._liveness.get(EMPTY_UUID, key) is not None
        except Exception as error:
            log.warning("heartbeat not published: %r", error)
            stored = False
        if stored and not self.online:
            log.info("heartbeat published")
        elif not stored and self.online:
            log.warning("heartbeat no longer published; claiming continues")
        self.online = stored

    async def _mark_offline(self) -> None:
        """Bounded like a beat: a key that cannot be removed expires on its own."""
        key = f"worker:{self._options.worker_id}"
        try:
            async with asyncio.timeout(self._options.heartbeat_interval.total_seconds()):
                await self._liveness.invalidate(EMPTY_UUID, key)
        except Exception as error:
            log.warning("could not mark offline; the liveness key expires on its own: %r", error)
        self.online = False

    # Maintenance.

    async def _sweep_forever(self) -> None:
        while True:
            await self._sweep_once()
            await asyncio.sleep(self._options.sweep_interval.total_seconds())

    async def _sweep_once(self) -> None:
        """First the cross-tenant steps that bound recovery: the expired
        leases go back to the queue, and the outbox rows a crash or an outage
        left are relayed. Then one service context per tenant, the system
        scope first and deleted tenants included (their purges run there),
        and every step under each; then the cross-tenant purges of the outbox
        and the queue. Every step is idempotent and wrapped, so a failing
        tenant or step never stops the rest.

        The pass has a budget. The requeue and the relay run on every pass,
        each again while its batch comes back full and the budget lasts, so
        a crashed worker's item waits one pass at most and a backlog drains
        at the pace the budget allows. The pass takes no new tenant once the
        budget is spent, but always takes one, and the next pass starts at
        the tenant this one stopped at, so every tenant is reached in turn
        however many there are. A tenant it takes runs every step at least
        once; a step whose batch came back full runs again, in turn with the
        others, while the budget lasts. The cross-tenant purges run on every
        pass."""
        clock = asyncio.get_running_loop().time
        started = clock()
        deadline = started + self._options.sweep_budget.total_seconds()
        rctx = self._request()
        try:
            await self._while_full(
                lambda: self._work.requeue_stale(rctx, self._options.requeue_batch),
                self._options.requeue_batch,
                deadline,
            )
        except Exception:
            log.exception("sweep: requeue_stale failed")
        try:
            # Whatever a crash left between the core write and its push. A
            # batch with a row that failed is not full, so a destination that
            # is down is not asked again in this pass.
            await self._while_full(
                lambda: self._outbox.relay_pending(self._options.outbox_batch),
                self._options.outbox_batch,
                deadline,
            )
        except Exception:
            log.exception("sweep: outbox relay failed")
        try:
            contexts = await self._work.maintenance_contexts(rctx)
        except Exception:
            log.exception("sweep: maintenance_contexts failed")
            contexts = []
        ring = self._from_resume_point(contexts)
        swept = 0
        self._resume_at = None
        for ctx in ring:
            if swept and clock() >= deadline:
                self._resume_at = ctx.org_id
                break
            await self._sweep_tenant(ctx, deadline)
            swept += 1
        try:
            await self._while_full(
                lambda: self._outbox.purge_done(
                    self._options.outbox_retention, self._options.purge_batch
                ),
                self._options.purge_batch,
                deadline,
            )
        except Exception:
            log.exception("sweep: outbox purge failed")
        try:
            purged = await self._while_full(
                self._work.purge_items, self._options.purge_batch, deadline
            )
            if purged:
                log.info("sweep: purged %d settled work items", purged)
        except Exception:
            log.exception("sweep: work item purge failed")
        self.sweeps += 1
        seconds = clock() - started
        SWEEP_SECONDS.observe(seconds)
        # One line per pass, its numbers as fields: the alarms module's log
        # filter reads the duration off it.
        log.info(
            "sweep: pass took %.3fs over %d of %d tenants%s",
            seconds,
            swept,
            len(ring),
            "" if self._resume_at is None else f"; the next resumes at {self._resume_at}",
            extra={
                "sweep": {
                    "duration_ms": round(seconds * 1000),
                    "tenants": swept,
                    "of": len(ring),
                    "finished": self._resume_at is None,
                }
            },
        )

    def _from_resume_point(self, contexts: list[OpContext]) -> list[OpContext]:
        """The pass's tenants in id order, the system scope first, turned to
        start at the tenant the last pass stopped at. A tenant that went from
        the list since starts the pass at the next one."""
        ordered = sorted(contexts, key=lambda ctx: ctx.org_id)
        if self._resume_at is None:
            return ordered
        at = next((i for i, ctx in enumerate(ordered) if ctx.org_id >= self._resume_at), 0)
        return ordered[at:] + ordered[:at]

    async def _sweep_tenant(self, ctx: OpContext, deadline: float) -> None:
        """Every step and every chore of one tenant once, then the steps whose batch came back
        full, round after round, while the budget lasts. A deleted tenant for
        which nothing was left anywhere is marked purged, and the sweep leaves
        it out from then on."""
        settled = True
        full: list[tuple[str, PurgeStep]] = []
        for name, purge in self._purges.items():
            purged = await self._purge(ctx, name, purge)
            settled = settled and purged == 0
            if purged is not None and purged >= self._options.purge_batch:
                full.append((name, purge))
        # The standing chores run once whenever the tenant does, before any
        # second round of purges, so no budget spent on a backlog skips them.
        for name, chore in self._chores.items():
            try:
                await chore(ctx)
            except Exception:
                settled = False
                log.exception("sweep: %s failed for tenant %s", name, ctx.org_id)
        clock = asyncio.get_running_loop().time
        while full and clock() < deadline:
            again, full = full, []
            for name, purge in again:
                purged = await self._purge(ctx, name, purge)
                if purged is not None and purged >= self._options.purge_batch:
                    full.append((name, purge))
        if settled:
            try:
                if await self._work.mark_purged(ctx):
                    log.info("sweep: nothing is left of deleted org %s; marked purged", ctx.org_id)
            except Exception:
                log.exception("sweep: mark_purged failed for tenant %s", ctx.org_id)

    @staticmethod
    async def _purge(ctx: OpContext, name: str, purge: PurgeStep) -> int | None:
        """One call of one step; None when it failed, which it logs."""
        try:
            purged = await purge(ctx)
        except Exception:
            log.exception("sweep: %s purge failed for tenant %s", name, ctx.org_id)
            return None
        if purged:
            log.info("sweep: purged %d %s rows in org %s", purged, name, ctx.org_id)
        return purged

    @staticmethod
    async def _while_full(step: Callable[[], Awaitable[int]], batch: int, deadline: float) -> int:
        """A cross-tenant step, called again while its batch comes back full
        and the budget lasts; returns how many rows it moved in all."""
        clock = asyncio.get_running_loop().time
        moved = await step()
        total = moved
        while moved >= batch and clock() < deadline:
            moved = await step()
            total += moved
        return total

    # Shutdown.

    async def _drain(self) -> None:
        """Cancels every running item and awaits them all: one whose return is
        refused by a database that is down ends with an error, which
        `_on_item_done` logs, and stops none of the others."""
        # One turn of the loop first, so a task the claim created as `stop()`
        # arrived has taken its first step. Cancelling one that never ran
        # raises at its first instruction, outside the `except CancelledError`
        # that returns the item, and the item would sit CLAIMED by a worker
        # that is gone until its lease expired.
        await asyncio.sleep(0)
        tasks = list(self._running)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
