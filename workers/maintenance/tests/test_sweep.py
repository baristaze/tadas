"""The sweep's pass: the requeue of expired leases and the outbox relay, once
a pass across tenants and again while a batch comes back full, its budget and
where the next pass resumes, a purge called again while its batch comes back
full, each namespace's purge past its retention once a pass across tenants,
a living tenant that costs the purges nothing, a deleted tenant marked purged
once nothing of it is left and left out after, the tenant's expiry read once
per pass, and the pass's duration on its own line."""

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from worker_support import build_container, fast_options, request

from tadas.infra.cache import CacheScope
from tadas.infra.observability import JsonFormatter
from tadas.om.base import EMPTY_UUID, new_id, utcnow
from tadas.om.opcontext import CredentialKind, OpContext, RequestContext, Role, build_context
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.role import permissions_of
from tadas.om.work import WorkManagerInterface
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.loop import AcrossStep, LoopOptions, PurgeStep, WorkerLoop
from tadas.workers.maintenance.main import build_loop


class Tenants(WorkManagerInterface):
    """The part of the work manager the sweep asks: a fixed list of tenants,
    the counts the requeue returns in turn (nothing stale unless given),
    nothing to purge across tenants, and a record of the calls in order and
    of the tenants it was asked to mark purged. A partial double."""

    def __init__(self, contexts: Sequence[OpContext], requeued: Sequence[int] = (0,)) -> None:
        self.contexts = list(contexts)
        self.marked: list[UUID] = []
        self.requeued = list(requeued)
        self.calls: list[str] = []

    async def maintenance_contexts(self, rctx: RequestContext) -> list[OpContext]:
        self.calls.append("contexts")
        return list(self.contexts)

    async def requeue_stale(self, rctx: RequestContext, limit: int) -> int:
        self.calls.append("requeue")
        return self.requeued.pop(0) if len(self.requeued) > 1 else self.requeued[0]

    async def purge_items(self) -> int:
        return 0

    async def mark_purged(self, ctx: OpContext) -> bool:
        self.marked.append(ctx.org_id)
        return False


Tenants.__abstractmethods__ = frozenset()


def listed(contexts: Sequence[OpContext], requeued: Sequence[int] = (0,)) -> Tenants:
    return Tenants(contexts, requeued)  # pyright: ignore[reportAbstractUsage] (a partial double)


class Outbox(OutboxRelayInterface):
    """The part of the relay the sweep asks: the counts the relay returns in
    turn (nothing pending unless given), counting its relays and its purges.
    A partial double."""

    def __init__(self, relayed: Sequence[int] = (0,)) -> None:
        self.purges = 0
        self.relays = 0
        self.relayed = list(relayed)

    async def relay_pending(self, limit: int) -> int:
        self.relays += 1
        return self.relayed.pop(0) if len(self.relayed) > 1 else self.relayed[0]

    async def purge_done(self, retention: timedelta, limit: int) -> int:
        self.purges += 1
        return 0


Outbox.__abstractmethods__ = frozenset()


def quiet_outbox(relayed: Sequence[int] = (0,)) -> Outbox:
    return Outbox(relayed)  # pyright: ignore[reportAbstractUsage] (a partial double)


def service_contexts(count: int) -> list[OpContext]:
    """The system scope and `count` tenants, as the sweep receives them."""
    rctx = request()
    return [
        build_context(
            rctx,
            user_id=EMPTY_UUID,
            org_id=org_id,
            role=Role.SERVICE,
            permissions=permissions_of(Role.SERVICE),
            credential_kind=CredentialKind.INTERNAL,
        )
        for org_id in [EMPTY_UUID, *(new_id() for _ in range(count))]
    ]


def sweeping(
    container: WorkerContainer,
    work: WorkManagerInterface,
    purges: dict[str, PurgeStep],
    options: LoopOptions,
    outbox: OutboxRelayInterface | None = None,
    chores: dict[str, PurgeStep] | None = None,
    across: dict[str, AcrossStep] | None = None,
) -> WorkerLoop:
    return WorkerLoop(
        work=work,
        outbox=outbox or quiet_outbox(),
        purges=purges,
        chores=chores,
        across=across,
        handlers={},
        topics=container.infra.get_topics(),
        liveness=container.infra.get_cache(CacheScope.WORKER_LIVENESS),
        options=options,
    )


def recording(
    calls: list[tuple[str, UUID]], name: str, counts: Sequence[int] = (0,)
) -> Callable[[OpContext], Awaitable[int]]:
    """A purge step that records each call and returns `counts` in turn, the
    last of them for ever after."""
    left = list(counts)

    async def step(ctx: OpContext) -> int:
        calls.append((name, ctx.org_id))
        return left.pop(0) if len(left) > 1 else left[0]

    return step


async def test_a_spent_budget_stops_the_pass_and_the_next_resumes_where_it_stopped(
    tmp_path: Path,
) -> None:
    """With no budget at all a pass takes one tenant, never none, and runs
    every step of it; the next pass takes the next tenant. Every tenant is
    reached in turn, the system scope among them, and no step is skipped for
    any of them. The cross-tenant steps run on every pass."""
    container = build_container(tmp_path)
    contexts = service_contexts(3)
    calls: list[tuple[str, UUID]] = []
    outbox = quiet_outbox()
    loop = sweeping(
        container,
        listed(contexts),
        {"one": recording(calls, "one"), "two": recording(calls, "two")},
        fast_options(sweep_budget=timedelta(0)),
        outbox,
    )
    for _ in range(len(contexts) + 1):
        await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    ids = [ctx.org_id for ctx in sorted(contexts, key=lambda ctx: ctx.org_id)]
    expected = [(name, org_id) for org_id in [*ids, ids[0]] for name in ("one", "two")]
    assert calls == expected, "a tenant a pass, in turn, round to the first again"
    assert outbox.purges == len(contexts) + 1, "the outbox purge ran on every pass"


async def test_a_pass_within_its_budget_reaches_every_tenant(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    contexts = service_contexts(3)
    calls: list[tuple[str, UUID]] = []
    loop = sweeping(container, listed(contexts), {"one": recording(calls, "one")}, fast_options())
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert sorted(org for _, org in calls) == sorted(ctx.org_id for ctx in contexts)


async def test_a_full_batch_is_purged_again_while_the_budget_lasts(tmp_path: Path) -> None:
    """A purge that returns a whole batch may have more; it is called again,
    in turn with the other full ones, until it returns less. A purge that
    returned less is drained and not called again."""
    container = build_container(tmp_path)
    (system,) = service_contexts(0)
    calls: list[tuple[str, UUID]] = []
    loop = sweeping(
        container,
        listed([system]),
        {
            "backlog": recording(calls, "backlog", (2, 2, 1)),
            "drained": recording(calls, "drained", (1,)),
            "other backlog": recording(calls, "other backlog", (3, 0)),
        },
        fast_options(purge_batch=2),
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert [name for name, _ in calls] == [
        "backlog",
        "drained",
        "other backlog",
        "backlog",
        "other backlog",
        "backlog",
    ]


async def test_a_spent_budget_leaves_a_full_batch_for_the_next_pass(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    (system,) = service_contexts(0)
    calls: list[tuple[str, UUID]] = []
    loop = sweeping(
        container,
        listed([system]),
        {"backlog": recording(calls, "backlog", (2,))},
        fast_options(purge_batch=2, sweep_budget=timedelta(0)),
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == 2, "one batch a pass"


async def test_only_a_tenant_with_nothing_left_is_offered_to_be_marked_purged(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    busy, idle, failing = service_contexts(3)[1:]
    work = listed([busy, idle, failing])
    calls: list[tuple[str, UUID]] = []

    async def step(ctx: OpContext) -> int:
        calls.append(("step", ctx.org_id))
        if ctx.org_id == failing.org_id:
            raise RuntimeError("the database is down")
        return 1 if ctx.org_id == busy.org_id else 0

    loop = sweeping(container, work, {"step": step}, fast_options())
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert work.marked == [idle.org_id]


async def deleted_org(container: WorkerContainer, days_ago: int) -> UUID:
    """A team org deleted `days_ago`, with one removed member's rows left."""
    tail = new_id().hex[-8:]
    _, org = await container.managers.tenancy.bootstrap(
        request(), "Gone", f"gone-{tail}", f"gone-{tail}@example.test", "Gone"
    )
    storage = container.storage.get_tenancy_storage()
    stored = await storage.read_org(org.id)
    assert stored is not None
    when = utcnow() - timedelta(days=days_ago)
    await storage.write_org(org.id, stored.model_copy(update={"deleted_at": when}))
    return org.id


async def test_a_deleted_tenant_is_marked_purged_once_nothing_is_left_and_skipped_after(
    tmp_path: Path,
) -> None:
    """The first pass takes the rows of a tenant past its retention, the next
    finds nothing left and marks it, and from then on the sweep leaves it
    out. A tenant within its retention is swept and never marked."""
    container = build_container(tmp_path)
    expired = await deleted_org(container, days_ago=40)
    recent = await deleted_org(container, days_ago=1)
    loop = build_loop(container)
    tenancy = container.storage.get_tenancy_storage()

    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    first = await tenancy.read_org(expired)
    assert first is not None and first.purged_at is None, "this pass took its rows"
    assert await tenancy.read_users(expired, None, limit=10) == []

    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    marked = await tenancy.read_org(expired)
    assert marked is not None and marked.purged_at is not None, "nothing was left"
    kept = await tenancy.read_org(recent)
    assert kept is not None and kept.purged_at is None, "within its retention"

    swept = {ctx.org_id for ctx in await container.managers.work.maintenance_contexts(request())}
    assert expired not in swept, "a purged tenant is left out"
    assert recent in swept and EMPTY_UUID in swept


async def test_a_pass_reads_no_org_row_to_ask_whether_a_tenant_expired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every namespace's purge asks whether its tenant is past the retention;
    the pass answers from the org rows it read to list the tenants, so no
    purge reads the org row again."""
    container = build_container(tmp_path)
    await deleted_org(container, days_ago=40)
    await deleted_org(container, days_ago=1)
    storage = container.storage.get_tenancy_storage()
    reads: list[UUID] = []
    read_org = storage.read_org

    async def counted(org_id: UUID) -> Org | None:
        reads.append(org_id)
        return await read_org(org_id)

    monkeypatch.setattr(storage, "read_org", counted)
    await build_loop(container)._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert reads == []


async def test_a_pass_says_how_long_it_took_on_one_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    container = build_container(tmp_path)
    contexts = service_contexts(2)
    loop = sweeping(
        container,
        listed(contexts),
        {"one": recording([], "one")},
        fast_options(sweep_budget=timedelta(0)),
    )
    with caplog.at_level(logging.INFO, logger="tadas.workers.maintenance.loop"):
        await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    (record,) = [r for r in caplog.records if hasattr(r, "sweep")]
    line = json.loads(JsonFormatter().format(record))
    assert line["sweep"]["tenants"] == 1 and line["sweep"]["of"] == 3
    assert line["sweep"]["finished"] is False
    assert isinstance(line["sweep"]["duration_ms"], int)


async def test_a_backlog_spends_no_budget_a_chore_needs(tmp_path: Path) -> None:
    """With no budget left and a purge whose batch keeps coming back full,
    every tenant a pass takes still runs its chores (the day's cleanup
    opening among them), once, before any second round of purges."""
    container = build_container(tmp_path)
    contexts = service_contexts(2)
    calls: list[tuple[str, UUID]] = []
    loop = sweeping(
        container,
        listed(contexts),
        {"backlog": recording(calls, "backlog", (2,))},
        fast_options(purge_batch=2, sweep_budget=timedelta(0)),
        chores={"cleanup": recording(calls, "cleanup")},
    )
    for _ in range(len(contexts)):
        await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    ids = sorted(ctx.org_id for ctx in contexts)
    assert calls == [(name, org_id) for org_id in ids for name in ("backlog", "cleanup")]


async def test_the_requeue_runs_once_a_pass_across_tenants_before_any_tenant(
    tmp_path: Path,
) -> None:
    """However many tenants there are, and with no budget at all, a pass
    requeues expired leases in one call, before it lists the tenants, so a
    crashed worker's item waits one pass and not its tenant's turn."""
    container = build_container(tmp_path)
    work = listed(service_contexts(3))
    calls: list[tuple[str, UUID]] = []
    loop = sweeping(
        container,
        work,
        {"one": recording(calls, "one")},
        fast_options(sweep_budget=timedelta(0)),
    )
    for _ in range(2):
        await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert work.calls == ["requeue", "contexts", "requeue", "contexts"]
    assert len(calls) == 2, "a tenant a pass, and the requeue in none of them"


async def test_a_full_requeue_batch_is_requeued_again_while_the_budget_lasts(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    work = listed(service_contexts(0), requeued=(2, 2, 1))
    loop = sweeping(container, work, {}, fast_options(requeue_batch=2))
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert work.calls == ["requeue", "requeue", "requeue", "contexts"]

    spent = listed(service_contexts(0), requeued=(2,))
    loop = sweeping(container, spent, {}, fast_options(requeue_batch=2, sweep_budget=timedelta(0)))
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert spent.calls == ["requeue", "contexts"], "past the budget, one batch a pass"


async def test_the_relay_runs_again_while_its_batch_comes_back_full(tmp_path: Path) -> None:
    """A backlog of pending rows, after a crash or an outage of the bus,
    drains at the pace of the budget and not of one batch a pass. A batch
    that came back short, a row failing in it among the reasons, ends it."""
    container = build_container(tmp_path)
    outbox = quiet_outbox(relayed=(2, 2, 1, 2))
    loop = sweeping(
        container, listed(service_contexts(0)), {}, fast_options(outbox_batch=2), outbox
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert outbox.relays == 3

    spent = quiet_outbox(relayed=(2,))
    loop = sweeping(
        container,
        listed(service_contexts(0)),
        {},
        fast_options(outbox_batch=2, sweep_budget=timedelta(0)),
        spent,
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert spent.relays == 2, "past the budget, one batch a pass"


def across_recording(
    calls: list[str], name: str, counts: Sequence[int] = (0,)
) -> Callable[[RequestContext], Awaitable[int]]:
    """A purge across tenants that records each call and returns `counts` in
    turn, the last of them for ever after."""
    left = list(counts)

    async def step(rctx: RequestContext) -> int:
        calls.append(name)
        return left.pop(0) if len(left) > 1 else left[0]

    return step


async def test_each_purge_across_tenants_runs_once_a_pass_after_the_tenants(
    tmp_path: Path,
) -> None:
    """However many tenants there are, and with no budget at all, a pass runs
    each namespace's purge past its retention once, after the tenants it
    takes, under the pass's one request stage."""
    container = build_container(tmp_path)
    calls: list[str] = []
    stages: set[UUID] = set()

    async def events(rctx: RequestContext) -> int:
        calls.append("events")
        stages.add(rctx.request_id)
        return 0

    async def tenant(ctx: OpContext) -> int:
        calls.append("tenant")
        stages.add(ctx.request_id)
        return 0

    work = listed(service_contexts(3))
    loop = sweeping(
        container,
        work,
        {"tenant": tenant},
        fast_options(sweep_budget=timedelta(0)),
        across={"tasks": across_recording(calls, "tasks"), "events": events},
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert calls == ["tenant", "tasks", "events"], "one tenant, then each purge once"
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert calls[3:] == ["tenant", "tasks", "events"]


async def test_a_full_purge_across_tenants_runs_again_while_the_budget_lasts(
    tmp_path: Path,
) -> None:
    """A purge whose batch came back whole may have more: it runs again, in
    turn with the other full ones, until it comes back short. Past the
    budget, each runs once a pass, and the next pass takes the rest."""
    container = build_container(tmp_path)
    calls: list[str] = []
    loop = sweeping(
        container,
        listed(service_contexts(0)),
        {},
        fast_options(purge_batch=2),
        across={
            "backlog": across_recording(calls, "backlog", (2, 2, 1)),
            "drained": across_recording(calls, "drained", (1,)),
            "other backlog": across_recording(calls, "other backlog", (3, 0)),
        },
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert calls == [
        "backlog",
        "drained",
        "other backlog",
        "backlog",
        "other backlog",
        "backlog",
    ]

    spent: list[str] = []
    loop = sweeping(
        container,
        listed(service_contexts(0)),
        {},
        fast_options(purge_batch=2, sweep_budget=timedelta(0)),
        across={"backlog": across_recording(spent, "backlog", (2,))},
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert spent == ["backlog", "backlog"], "past the budget, one batch a pass"


async def test_a_purge_across_tenants_with_a_batch_of_its_own_is_full_at_it(
    tmp_path: Path,
) -> None:
    """The media purge erases an object per row, so its batch is smaller than
    the rows' batch; a whole one of its own is full, and it runs again."""
    container = build_container(tmp_path)
    calls: list[str] = []
    loop = WorkerLoop(
        work=listed(service_contexts(0)),
        outbox=quiet_outbox(),
        purges={},
        across={
            "media": across_recording(calls, "media", (1, 1, 0)),
            "rows": across_recording(calls, "rows", (1, 0)),
        },
        across_batches={"media": 1},
        handlers={},
        topics=container.infra.get_topics(),
        liveness=container.infra.get_cache(CacheScope.WORKER_LIVENESS),
        options=fast_options(purge_batch=2),
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert calls == ["media", "rows", "media", "media"]


async def test_a_failing_purge_across_tenants_stops_no_other_step(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    calls: list[str] = []

    async def failing(rctx: RequestContext) -> int:
        raise RuntimeError("the database is down")

    outbox = quiet_outbox()
    loop = sweeping(
        container,
        listed(service_contexts(1)),
        {"tenant": recording([], "tenant")},
        fast_options(),
        outbox,
        across={"failing": failing, "after": across_recording(calls, "after")},
    )
    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]
    assert calls == ["after"]
    assert outbox.purges == 1, "the outbox purge still ran"


PURGE_READS = (
    "read_deleted",
    "purge_deleted",
    "read_purgeable",
    "purge_files_across_tenants",
    "purge_records",
    "purge_sign_in_delays",
    "trim",
    "purge_deliveries",
    "purge",
    "purge_settled",
)
"""The storage methods of the purges past a retention, across tenants."""


async def test_a_living_tenant_costs_the_purges_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the worker's own wiring and three living tenants, a pass sends
    each purge past its retention once for every tenant, and no purge
    statement at all for any one tenant: a living tenant's own purge answers
    from the expiry the pass read with the org rows."""
    container = build_container(tmp_path)
    for slug in ("acme", "beta", "gamma"):
        await container.managers.tenancy.bootstrap(
            request(), slug.title(), slug, f"ann@{slug}.test", "Ann"
        )
    storage = container.storage
    calls: list[str] = []
    for namespace in (
        storage.get_tasks_storage(),
        storage.get_media_storage(),
        storage.get_tenancy_storage(),
        storage.get_idempotency_storage(),
        storage.get_event_storage(),
        storage.get_billing_storage(),
        storage.get_slack_storage(),
        storage.get_orchestrations_storage(),
    ):
        for name in (*PURGE_READS, "purge_tenant", "read_every_file"):
            method = getattr(namespace, name, None)
            if method is None:
                continue

            def counted(
                method: Callable[..., Awaitable[object]] = method,
                label: str = f"{type(namespace).__name__}.{name}",
            ) -> Callable[..., Awaitable[object]]:
                async def call(*args: object, **kwargs: object) -> object:
                    calls.append(label)
                    return await method(*args, **kwargs)

                return call

            monkeypatch.setattr(namespace, name, counted())
    await build_loop(container)._sweep_once()  # pyright: ignore[reportPrivateUsage]
    per_tenant = [c for c in calls if c.endswith((".purge_tenant", ".read_every_file"))]
    assert per_tenant == [], "no living tenant is purged in its own right"
    assert len(calls) == len(set(calls)), f"each purge once a pass: {calls}"
    assert len(calls) == 11, calls
