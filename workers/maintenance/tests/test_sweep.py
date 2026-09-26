"""The sweep's pass: the requeue of expired leases, once a pass across
tenants and again while its batch comes back full, its budget and
where the next pass resumes, a purge called again while its batch comes back
full, a deleted tenant marked purged once nothing of it is left and left out
after, the tenant's expiry read once per pass, and the pass's duration on its
own line."""

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
from tadas.workers.maintenance.loop import LoopOptions, PurgeStep, WorkerLoop
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
) -> WorkerLoop:
    return WorkerLoop(
        work=work,
        outbox=outbox or quiet_outbox(),
        purges=purges,
        chores=chores,
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
