"""The sweep's relay: a poison row stops nothing behind it, and a row whose
attempts are spent is a dead letter, failed for good, counted, and named by
an audit event."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.outbox_storage import claim_all, make_row
from contracts.task_storage import make_task
from opentelemetry.sdk.trace import TracerProvider

from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.observability import OUTCOMES
from tadas.infra.topics import TopicPayload, Topics
from tadas.om.base import EMPTY_UUID, new_id, utcnow
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.events.types.event import Event
from tadas.om.opcontext import AppContext, AppType, OpContext, RequestContext
from tadas.om.outbox.impl.relay import DEAD_LETTER_KIND, OutboxOptions, OutboxRelayImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.outbox.types.row import outbox_row, snapshot
from tadas.om.root import Managers, build_managers
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.tasks.storage.impl.memory import TasksStorageMemoryImpl
from tadas.om.tenancy.impl.manager import TenancyOptions
from tadas.om.work.types.work_item import WorkKind, work_row_kind

NO_GRACE = OutboxOptions(grace=timedelta(0), backoff_base=timedelta(0), max_attempts=2)


class PoisonedEvents(EventStorageMemoryImpl):
    """The append refuses one row's event, as a bad payload downstream would."""

    def __init__(self, poison_id: UUID) -> None:
        super().__init__()
        self.poison_id = poison_id

    async def append_event(self, org_id: UUID, event: Event) -> Event:
        if event.id == self.poison_id:
            raise RuntimeError("cannot append this one")
        return await super().append_event(org_id, event)


@pytest.fixture
def infra(tmp_path: Path) -> InfraLocalImpl:
    return InfraLocalImpl(tmp_path)


async def test_the_row_carries_the_trace_context_of_the_write_or_none(
    infra: InfraLocalImpl,
) -> None:
    """The row names the request that made the write and the trace context of
    that request, as the header the far side links to. With no tracer
    configured the header is empty, and the far side starts its own trace."""
    managers = build_managers(StorageMemoryImpl(), infra, TenancyOptions(dev_sign_in=True))
    ctx = await sign_in(managers)
    task = make_task(created_by=ctx.user_id)
    assert outbox_row(ctx, "tasks.task.created", task.id, snapshot(task)).traceparent is None
    tracer = TracerProvider().get_tracer("tadas.om.tests")
    with tracer.start_as_current_span("POST /tasks") as span:
        row = outbox_row(ctx, "tasks.task.created", task.id, snapshot(task))
    assert row.request_id == ctx.request_id
    assert row.traceparent is not None
    assert f"{span.get_span_context().trace_id:032x}" in row.traceparent


def dead_letters() -> float:
    return OUTCOMES.labels(subsystem="outbox", outcome="dead_letter")._value.get()


async def test_a_poison_row_does_not_block_the_rows_behind_it_and_dies_after_max_attempts(
    infra: InfraLocalImpl,
) -> None:
    outbox = OutboxStorageMemoryImpl()
    tasks = TasksStorageMemoryImpl(outbox)
    org = new_id()
    poison, fine = make_task(), make_task()
    poison_row, fine_row = make_row(org, poison.id), make_row(org, fine.id)
    await tasks.create_task(org, poison, (poison_row,))
    await tasks.create_task(org, fine, (fine_row,))
    events = PoisonedEvents(poison_row.id)
    relay = OutboxRelayImpl(outbox, events, infra.get_topics(), options=NO_GRACE)
    counted = dead_letters()

    # First sweep: the fine row is relayed although the poison row is older.
    assert await relay.relay_pending(10) == 1
    stored = {r.id: r for _, r in outbox._rows.values()}
    assert stored[fine_row.id].done_at is not None
    failed = stored[poison_row.id]
    assert failed.done_at is None and failed.failed_at is None and failed.attempts == 1
    assert failed.last_error == "RuntimeError: cannot append this one"
    assert dead_letters() == counted
    assert [e.kind for e in await events.read_after(org, 0, 10)] == ["tasks.task.created"]

    # Second sweep: the last attempt is spent; the row is a dead letter with
    # an audit event under the row's own provenance, and is never claimed again.
    assert await relay.relay_pending(10) == 0
    failed = {r.id: r for _, r in outbox._rows.values()}[poison_row.id]
    assert failed.failed_at is not None and failed.attempts == 2
    assert dead_letters() == counted + 1
    audit = [e for e in await events.read_after(org, 0, 10) if e.kind == DEAD_LETTER_KIND]
    assert len(audit) == 1
    assert audit[0].target_id == poison_row.id and audit[0].actor_id == poison_row.actor_id
    assert audit[0].payload["attempts"] == 2 and audit[0].payload["kind"] == poison_row.kind
    assert await claim_all(outbox) == []
    assert await relay.relay_pending(10) == 0
    assert dead_letters() == counted + 1


async def test_the_sweep_leaves_a_row_younger_than_the_grace(infra: InfraLocalImpl) -> None:
    outbox = OutboxStorageMemoryImpl()
    tasks = TasksStorageMemoryImpl(outbox)
    org = new_id()
    task = make_task()
    row = make_row(org, task.id, age=timedelta(0))
    await tasks.create_task(org, task, (row,))
    relay = OutboxRelayImpl(outbox, EventStorageMemoryImpl(), infra.get_topics())
    assert await relay.relay_pending(10) == 0, "the request path relays a fresh row"
    assert await relay.relay(org, row)
    assert await claim_all(outbox) == []


async def test_purge_takes_done_and_failed_rows_past_the_retention(infra: InfraLocalImpl) -> None:
    outbox = OutboxStorageMemoryImpl()
    tasks = TasksStorageMemoryImpl(outbox)
    org = new_id()
    done, failed = make_task(), make_task()
    done_row, failed_row = make_row(org, done.id), make_row(org, failed.id)
    await tasks.create_task(org, done, (done_row,))
    await tasks.create_task(org, failed, (failed_row,))
    await outbox.mark_done(org, done_row.id)
    await outbox.record_failure(org, failed_row.id, "for good", utcnow())
    relay = OutboxRelayImpl(outbox, EventStorageMemoryImpl(), infra.get_topics())
    assert await relay.purge_done(timedelta(hours=1), 1000) == 0
    assert await relay.purge_done(timedelta(seconds=-1), 1000) == 2


async def sign_in(managers: Managers) -> OpContext:
    """A tenant with a member, so a relayed work item has a principal to run
    under: the row names the actor and the claim rebuilds it."""
    tenancy = managers.tenancy
    app = AppContext(type=AppType.PORTAL, version="portal@test")

    def request() -> RequestContext:
        return RequestContext(request_id=new_id(), app=app)

    _, org = await tenancy.bootstrap(request(), "Acme", "acme", "ann@example.test", "Ann")
    login = await tenancy.dev_sign_in(request(), "ann@example.test")
    identity = await tenancy.authenticate_login(request(), login.token)
    issued = await tenancy.exchange_login(identity, org.id)
    return await tenancy.authenticate(request(), issued.token)


async def test_a_write_that_also_starts_work_rides_a_second_row_the_relay_enqueues(
    infra: InfraLocalImpl,
) -> None:
    """The write that also starts work, end to end. The entity change is one
    row; the work item rides a second row of kind `work.<kind>`, landed by the
    same statement, because the queue is a role of its own and no statement
    reaches both. The relay is what enqueues it, with no context and the actor
    from the row, and it presents the row's id as the item's idempotency key,
    which is the same on every run: a relay that runs twice leaves one item."""
    storage = StorageMemoryImpl()
    managers = build_managers(storage, infra, TenancyOptions(dev_sign_in=True))
    ctx = await sign_in(managers)
    woken: list[TopicPayload] = []

    async def record(payload: TopicPayload) -> None:
        woken.append(payload)

    infra.get_topics().subscribe(Topics.WORK_AVAILABLE, "test", record)

    task = make_task(created_by=ctx.user_id)
    tracer = TracerProvider().get_tracer("tadas.om.tests")
    with tracer.start_as_current_span("POST /tasks"):
        change = outbox_row(ctx, "tasks.task.created", task.id, snapshot(task))
        asked = outbox_row(ctx, work_row_kind(WorkKind.NOOP), task.id, {})
    assert await storage.get_tasks_storage().create_task(ctx.org_id, task, (change, asked))
    # One statement, two rows: the entity's change and the work it starts.
    landed = await claim_all(storage.get_outbox_storage())
    assert sorted(row.id for row in landed) == sorted([change.id, asked.id])

    assert await managers.outbox.relay(ctx.org_id, change)
    assert await managers.outbox.relay(ctx.org_id, asked)
    enqueued = await storage.get_work_storage().read_item_by_key(ctx.org_id, asked.id)
    assert enqueued is not None
    assert enqueued.kind is WorkKind.NOOP and enqueued.target_id == task.id
    assert enqueued.created_by == ctx.user_id, "the actor of the write that asked"
    assert enqueued.updated_by == EMPTY_UUID
    # The handoff carries the request that made the write and its trace
    # context; the relay mints neither, it reads both off the row.
    assert enqueued.request_id == asked.request_id == ctx.request_id
    assert enqueued.traceparent == asked.traceparent is not None
    assert len(woken) == 1

    # The sweep relays what it finds, and it finds this row again after a
    # crash between the enqueue and the mark. The key is the row's id on
    # every run, so the second enqueue meets the item already there.
    assert await managers.outbox.relay(ctx.org_id, asked)
    assert await storage.get_work_storage().read_item_by_key(ctx.org_id, asked.id) == enqueued
    assert len(woken) == 1, "the queue is woken once"
    claimed = await managers.work.claim(
        RequestContext(request_id=new_id(), app=AppContext(type=AppType.WORKER, version="w@test")),
        "default",
        [WorkKind.NOOP],
        "w1",
        timedelta(seconds=30),
    )
    assert claimed is not None and claimed[1].id == enqueued.id
    assert claimed[0].user_id == ctx.user_id, "the work runs under the person who asked"
    assert claimed[0].request_id != ctx.request_id, "the run is a request of its own"
    assert claimed[0].caused_by_request_id == ctx.request_id, "and it names its cause"
    assert (
        await managers.work.claim(
            RequestContext(
                request_id=new_id(), app=AppContext(type=AppType.WORKER, version="w@test")
            ),
            "default",
            [WorkKind.NOOP],
            "w2",
            timedelta(seconds=30),
        )
        is None
    ), "one row, not two"
