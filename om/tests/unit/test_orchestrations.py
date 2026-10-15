"""The orchestration mechanism on its own: its pure rules, the parse of an
import file, and the manager's start, wake, resume, failure, cancel, and
purge."""

from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from uuid import UUID

import pytest

from tadas.infra.impl.local import InfraLocalImpl
from tadas.om.base import new_id, utcnow
from tadas.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    RequestContext,
    Role,
    TenantContext,
    build_context,
)
from tadas.om.exceptions import NotAuthorized, NotFound, PreconditionFailed, ValidationFailed
from tadas.om.orchestrations.impl.manager import OrchestrationsOptions
from tadas.om.orchestrations.rules import (
    ROW_ERRORS_KEPT,
    advanced,
    cancelled,
    failed,
    is_settled,
    resumed,
    stagger,
    with_row_errors,
)
from tadas.om.orchestrations.steps import CREATED, UPDATED, orchestration_step_rows
from tadas.om.orchestrations.types.orchestration import (
    FailReason,
    Orchestration,
    OrchestrationKind,
    OrchestrationStatus,
    ParkReason,
    RowError,
)
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.root import Managers, build_managers
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.tasks.kinds import TasksOrchestrationKind
from tadas.om.tasks.rules import (
    ImportFileRefused,
    ImportRow,
    import_refusal,
    imported,
    parse_import,
    room_for,
)
from tadas.om.tenancy.rules import ROLE_PERMISSIONS
from tadas.om.work.impl.manager import not_before, relayed_key
from tadas.om.work.types.work_item import (
    OrchestrationPayload,
    WakeParkedPayload,
    WorkKind,
    work_row_kind,
)

APP = AppContext(type=AppType.PORTAL, version="portal@test")


def a_record(**fields: object) -> Orchestration:
    now = utcnow()
    actor = new_id()
    return Orchestration.model_validate(
        {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "created_by": actor,
            "updated_by": actor,
            "kind": TasksOrchestrationKind.TASK_IMPORT,
            "input": {"file_id": str(new_id())},
            **fields,
        }
    )


# The pure rules.


def test_a_step_moves_the_cursor_counts_its_skips_and_ends_the_record_when_last() -> None:
    record = a_record(skipped=1, row_errors=[{"row": 1, "reason": "malformed"}])
    now = utcnow()
    after = advanced(
        record, now, record.created_by, cursor=5, total=5,
        skipped=[RowError(row=4, reason="malformed")], finished=True,
    )  # fmt: skip
    assert (after.cursor, after.total, after.skipped) == (5, 5, 2)
    assert [e.row for e in after.row_errors] == [1, 4]
    assert after.status is OrchestrationStatus.SUCCEEDED and after.finished_at == now
    assert after.version == record.version + 1
    assert after.applied == record.applied  # the step's commit counts what it wrote


def test_a_guard_parks_the_record_at_its_cursor_keeping_what_it_made() -> None:
    record = a_record(applied=10, cursor=10)
    after = advanced(
        record, utcnow(), record.created_by, cursor=10, total=50, park=ParkReason.PLAN_LIMIT
    )
    assert after.status is OrchestrationStatus.PARKED
    assert after.park_reason is ParkReason.PLAN_LIMIT
    assert (after.cursor, after.applied, after.finished_at) == (10, 10, None)
    running = resumed(after, utcnow(), record.created_by)
    assert running.status is OrchestrationStatus.RUNNING and running.park_reason is None
    assert running.cursor == 10 and running.version == after.version + 1


def test_a_bound_fails_the_record_and_names_why() -> None:
    record = a_record()
    now = utcnow()
    ended = failed(record, now, record.created_by, FailReason.DEFECT)
    assert ended.status is OrchestrationStatus.FAILED
    assert ended.fail_reason is FailReason.DEFECT and ended.finished_at == now


def test_a_cancel_settles_the_record_keeping_what_it_made() -> None:
    record = a_record(
        status=OrchestrationStatus.PARKED, park_reason=ParkReason.LEASABLE_RESOURCE,
        cursor=7, total=9, applied=6, skipped=1, row_errors=[{"row": 3, "reason": "malformed"}],
    )  # fmt: skip
    now = utcnow()
    ended = cancelled(record, now, record.created_by)
    assert ended.status is OrchestrationStatus.CANCELLED and is_settled(ended)
    assert (ended.cursor, ended.total, ended.applied, ended.skipped) == (7, 9, 6, 1)
    assert ended.row_errors == record.row_errors
    assert (ended.park_reason, ended.fail_reason, ended.finished_at) == (None, None, now)
    assert ended.version == record.version + 1


def test_the_skipped_rows_named_are_bounded() -> None:
    kept = [RowError(row=n, reason="x") for n in range(ROW_ERRORS_KEPT - 1)]
    more = [RowError(row=100 + n, reason="y") for n in range(5)]
    bounded = with_row_errors(kept, more)
    assert len(bounded) == ROW_ERRORS_KEPT and bounded[-1].row == 100


def test_the_resumes_of_one_wake_are_staggered() -> None:
    assert [stagger(n, timedelta(seconds=2)) for n in range(3)] == [
        timedelta(0),
        timedelta(seconds=2),
        timedelta(seconds=4),
    ]


def test_room_is_what_the_plan_leaves_and_never_below_zero() -> None:
    assert room_for(None, 500) is None
    assert room_for(10, 7) == 3
    assert room_for(10, 12) == 0


def test_an_import_file_reads_its_known_columns_in_any_order() -> None:
    data = b"\xef\xbb\xbfNotes, Title ,extra,Due_On\nn1,First,x,2026-01-02\n,,,\n,Second,,\n"
    rows = parse_import(data, 1024)
    assert rows == [
        ImportRow(number=1, title="First", notes="n1", due_on="2026-01-02"),
        ImportRow(number=2, title="Second"),
    ]


@pytest.mark.parametrize(
    ("data", "bound", "rows", "reason"),
    [
        (b"title\n" + b"x\n" * 20, 10, 100, "file_too_large"),
        (b"title\n" + b"x\n" * 4, 1024, 3, "too_many_rows"),
        (b"title\x00\nx\n", 1024, 100, "not_csv"),
        (b"\xc3\x28 title\n", 1024, 100, "not_csv"),
        (b'title\n"unclosed\n', 1024, 100, "not_csv"),
        (b"name,notes\na,b\n", 1024, 100, "no_title_column"),
        (b"", 1024, 100, "no_title_column"),
    ],
)
def test_an_import_file_past_a_bound_is_refused(
    data: bytes, bound: int, rows: int, reason: str
) -> None:
    with pytest.raises(ImportFileRefused) as refused:
        parse_import(data, bound, rows)
    assert refused.value.reason == reason
    assert FailReason(reason)  # every refusal is a reason a record fails with


def test_a_row_is_refused_for_a_title_a_date_or_an_assignee() -> None:
    ann = new_id()
    members = {"ann@example.test": ann}
    assert import_refusal(ImportRow(number=1), members) == "no title"
    assert import_refusal(ImportRow(number=1, title="x" * 501), members) is not None
    assert import_refusal(ImportRow(number=1, title="t", due_on="2026-02-30"), members)
    assert import_refusal(ImportRow(number=1, title="t", due_on="26-02-01"), members)
    assert import_refusal(ImportRow(number=1, title="t", assignee_email="bob@x.test"), members)
    fine = ImportRow(number=3, title="t", due_on="2026-02-01", assignee_email="ANN@example.test")
    assert import_refusal(fine, members) is None
    made = imported(fine, members)
    assert made.assignee_id == ann and str(made.due_on) == "2026-02-01"


# The manager.


class World:
    def __init__(self, tmp_path: Path, options: OrchestrationsOptions | None = None) -> None:
        self.storage = StorageMemoryImpl()
        self.managers: Managers = build_managers(
            self.storage, InfraLocalImpl(tmp_path), orchestrations_options=options
        )

    async def org(self) -> TenantContext:
        slug = f"ajax-{new_id().hex[-8:]}"
        owner, _ = await self.managers.tenancy.bootstrap(
            RequestContext(request_id=new_id(), app=APP), "Ajax", slug, f"a-{slug}@x.test", "Ann"
        )
        return owner


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


async def test_start_holds_the_input_to_its_kind_and_answers_a_retry_as_stored(
    world: World,
) -> None:
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    with pytest.raises(ValidationFailed):
        await orchestrations.start(ctx, a_record(input={"file": "nope"}))
    record = a_record(cursor=99, status=OrchestrationStatus.FAILED)
    started = await orchestrations.start(ctx, record)
    # The steps' fields are the manager's: a start is running at its first cursor.
    assert (started.status, started.cursor, started.version) == (
        OrchestrationStatus.RUNNING,
        0,
        1,
    )
    assert await orchestrations.start(ctx, record) == started


async def test_a_noop_step_moves_the_cursor_by_one_and_succeeds_at_its_count(
    world: World,
) -> None:
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    record = await orchestrations.start(
        ctx, a_record(kind=OrchestrationKind.NOOP, input={"steps": 2})
    )
    first = await orchestrations.step_noop(ctx, record)
    assert (first.status, first.cursor, first.total) == (OrchestrationStatus.RUNNING, 1, 2)
    assert first.version == record.version + 1 and first.finished_at is None
    last = await orchestrations.step_noop(ctx, first)
    assert (last.status, last.cursor) == (OrchestrationStatus.SUCCEEDED, 2)
    assert last.finished_at is not None
    assert await orchestrations.get(ctx, record.id) == last


async def test_a_noop_step_is_conditioned_on_the_version_it_read(world: World) -> None:
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    record = await orchestrations.start(ctx, a_record(kind=OrchestrationKind.NOOP, input={}))
    stepped = await orchestrations.step_noop(ctx, record)
    with pytest.raises(PreconditionFailed):
        await orchestrations.step_noop(ctx, record)
    assert await orchestrations.get(ctx, record.id) == stepped


async def test_a_records_hint_names_the_version_its_write_left(world: World) -> None:
    """The push of a record's change names the version it wrote (ADR 0061),
    and a running record's write asks for its next step beside it."""
    ctx = await world.org()
    record = a_record(version=3)
    hint, work = orchestration_step_rows(ctx, record, created=True)
    assert (hint.kind, hint.target_id, hint.payload) == (CREATED, record.id, {"version": 3})
    assert work.kind == work_row_kind(WorkKind.ORCHESTRATION)
    settled = a_record(version=4, status=OrchestrationStatus.SUCCEEDED)
    assert [(r.kind, r.payload) for r in orchestration_step_rows(ctx, settled)] == [
        (UPDATED, {"version": 4})
    ]


async def test_wake_resumes_only_the_records_parked_for_the_reason(world: World) -> None:
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    storage = orchestrations._storage  # type: ignore[attr-defined]
    parked = await orchestrations.start(ctx, a_record())
    waiting = parked.model_copy(
        update={"status": OrchestrationStatus.PARKED, "park_reason": ParkReason.PLAN_LIMIT,
                "version": 2}
    )  # fmt: skip
    await storage.write_orchestration(ctx.org_id, waiting, 1, ())
    running = await orchestrations.start(ctx, a_record())
    assert await orchestrations.wake(ctx, ParkReason.PLAN_LIMIT) == 1
    assert (await orchestrations.get(ctx, parked.id)).status is OrchestrationStatus.RUNNING
    assert (await orchestrations.get(ctx, running.id)).version == running.version
    assert await orchestrations.wake(ctx, ParkReason.PLAN_LIMIT) == 0


async def test_the_parks_on_one_mark_land_one_wake_that_resumes_them_staggered(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each step that reads a provider's outage parks on `provider_unavailable`
    until the outage's retry time. The parks land one wake of the org's
    records, waiting in the queue until then, and it resumes them staggered:
    a provider that came back is not met by every parked record at once."""
    ctx = await world.org()
    orchestrations, work = world.managers.orchestrations, world.managers.work
    storage = world.storage.get_orchestrations_storage()
    written: list[OutboxRow] = []
    write = storage.write_orchestration

    async def writes(
        org_id: UUID, record: Orchestration, expected: int, rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        written.extend(rows)
        await write(org_id, record, expected, rows)

    monkeypatch.setattr(storage, "write_orchestration", writes)
    retry_at = utcnow() + timedelta(minutes=5)
    parks: list[Orchestration] = []
    for _ in range(3):
        record = await orchestrations.start(ctx, a_record())
        parked = advanced(
            record, utcnow(), record.created_by, cursor=0, total=3,
            park=ParkReason.PLAN_LIMIT,
        )  # fmt: skip
        await storage.write_orchestration(
            ctx.org_id,
            parked,
            record.version,
            orchestration_step_rows(ctx, parked, wake_at=retry_at),
        )
        parks.append(parked)
    wake_rows = [r for r in written if r.kind == work_row_kind(WorkKind.WAKE_PARKED)]
    assert len(wake_rows) == 3
    # The relay lands each row: the three parks are one item.
    landed = [await work.enqueue_relayed(row.org_id, row) for row in wake_rows]
    assert len({item.id for item in landed}) == 1
    wake = landed[0]
    assert wake.available_at == retry_at
    payload = WakeParkedPayload.model_validate(dict(wake.payload))
    assert payload == WakeParkedPayload(reason=ParkReason.PLAN_LIMIT, not_before=retry_at)

    # The item runs at the retry time: each record's next step a stagger
    # after the one before.
    written.clear()
    assert await orchestrations.wake(ctx, payload.reason, payload.record_id) == 3
    steps = sorted(
        OrchestrationPayload.model_validate(dict(row.payload)).not_before
        for row in written
        if row.kind == work_row_kind(WorkKind.ORCHESTRATION)
    )
    assert [later - earlier for earlier, later in pairwise(steps)] == [timedelta(seconds=2)] * 2

    # A park whose row lands once its time has passed keeps its own key and
    # runs at once: the wake its time named may have run before it parked.
    assert relayed_key(WorkKind.WAKE_PARKED, wake_rows[0], retry_at) == wake_rows[0].id
    # A park that names no time lands its hint alone, and a wake that names
    # none runs at once.
    assert len(orchestration_step_rows(ctx, parks[0])) == 1
    at_once = WakeParkedPayload(reason=ParkReason.PLAN_LIMIT)
    assert not_before(WakeParkedPayload, at_once.model_dump(mode="json")) is None


async def test_a_wake_resumes_every_record_parked_for_its_reason_a_batch_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wake reads the org's records parked for its reason a batch at a time
    until a batch comes back short: a record past the first batch resumes
    too, since no other wake may come for it, and the staggers go on across
    the batches."""
    batch = 2
    world = World(tmp_path, OrchestrationsOptions(wake_batch=batch))
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    storage = world.storage.get_orchestrations_storage()
    parks: list[Orchestration] = []
    for _ in range(batch + 1):
        record = await orchestrations.start(ctx, a_record())
        parked = advanced(
            record, utcnow(), record.created_by, cursor=0, total=3,
            park=ParkReason.PLAN_LIMIT,
        )  # fmt: skip
        await storage.write_orchestration(ctx.org_id, parked, record.version, ())
        parks.append(parked)
    written: list[OutboxRow] = []
    write = storage.write_orchestration

    async def writes(
        org_id: UUID, record: Orchestration, expected: int, rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        written.extend(rows)
        await write(org_id, record, expected, rows)

    monkeypatch.setattr(storage, "write_orchestration", writes)
    assert await orchestrations.wake(ctx, ParkReason.PLAN_LIMIT) == batch + 1
    for parked in parks:
        assert (await orchestrations.get(ctx, parked.id)).status is OrchestrationStatus.RUNNING
    steps = sorted(
        OrchestrationPayload.model_validate(dict(row.payload)).not_before
        for row in written
        if row.kind == work_row_kind(WorkKind.ORCHESTRATION)
    )
    assert [later - earlier for earlier, later in pairwise(steps)] == [timedelta(seconds=2)] * batch
    assert await orchestrations.wake(ctx, ParkReason.PLAN_LIMIT) == 0


async def test_fail_is_conditioned_on_the_version_it_read(world: World) -> None:
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    record = await orchestrations.start(ctx, a_record())
    ended = await orchestrations.fail(ctx, record, FailReason.DEFECT, "RuntimeError: boom")
    assert ended.fail_detail == "RuntimeError: boom"
    with pytest.raises(PreconditionFailed):
        await orchestrations.fail(ctx, record, FailReason.DEFECT)


async def test_a_record_of_another_org_is_not_found(world: World) -> None:
    ctx, other = await world.org(), await world.org()
    record = await world.managers.orchestrations.start(ctx, a_record())
    with pytest.raises(NotFound):
        await world.managers.orchestrations.get(other, record.id)
    with pytest.raises(NotFound):
        await world.managers.tasks.imports.get_import(other, record.id)


async def test_the_sweep_purges_settled_records_past_the_retention(world: World) -> None:
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    old = await orchestrations.start(ctx, a_record())
    ended = await orchestrations.fail(ctx, old, FailReason.DEFECT)
    storage = orchestrations._storage  # type: ignore[attr-defined]
    aged = ended.model_copy(
        update={"updated_at": utcnow() - timedelta(days=31), "version": ended.version + 1}
    )
    await storage.write_orchestration(ctx.org_id, aged, ended.version, ())
    live = await orchestrations.start(ctx, a_record())
    assert await orchestrations.purge_tenant(ctx) == 0, "a living tenant keeps its records"
    assert await orchestrations.purge_across_tenants() == 1
    with pytest.raises(NotFound):
        await orchestrations.get(ctx, old.id)
    assert (await orchestrations.get(ctx, live.id)).id == live.id


# The cancel.


async def parked_record(
    world: World, ctx: TenantContext, reason: ParkReason = ParkReason.PLAN_LIMIT
) -> Orchestration:
    """An import two rows in, parked on `reason` at its cursor, with a row it
    skipped and the row it applied."""
    orchestrations = world.managers.orchestrations
    record = await orchestrations.start(ctx, a_record())
    parked = advanced(
        record, utcnow(), record.created_by, cursor=2, total=3,
        skipped=[RowError(row=2, reason="malformed")], park=reason,
    ).model_copy(update={"applied": 1})  # fmt: skip
    await world.storage.get_orchestrations_storage().write_orchestration(
        ctx.org_id, parked, record.version, ()
    )
    return parked


def a_cleanup() -> Orchestration:
    """A day's cleanup with nothing old enough to archive: its first step is
    its last."""
    return a_record(
        kind=TasksOrchestrationKind.TASK_CLEANUP,
        input={"older_than_days": 90, "before": (utcnow() - timedelta(days=90)).isoformat()},
    )


async def test_a_person_cancels_a_parked_record_and_it_keeps_what_it_made(world: World) -> None:
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    parked = await parked_record(world, ctx)
    ended = await orchestrations.cancel(ctx, parked.id, "the wrong file")
    assert ended.status is OrchestrationStatus.CANCELLED and is_settled(ended)
    assert (ended.cursor, ended.total, ended.applied, ended.skipped) == (2, 3, 1, 1)
    assert ended.row_errors == parked.row_errors
    assert ended.finished_at is not None and ended.updated_by == ctx.user_id
    assert await orchestrations.get(ctx, parked.id) == ended
    # A second cancel answers the record as it is; a record that finished is
    # refused, since nothing is left to end.
    assert await orchestrations.cancel(ctx, parked.id, "again") == ended
    done = await orchestrations.start(ctx, a_cleanup())
    done = await world.managers.tasks.cleanup.step_cleanup(ctx, done)
    with pytest.raises(ValidationFailed):
        await orchestrations.cancel(ctx, done.id, "too late")
    assert (await orchestrations.get(ctx, done.id)).status is OrchestrationStatus.SUCCEEDED


async def test_a_step_in_flight_lands_nothing_after_a_cancel(world: World) -> None:
    """The step read the running record before the cancel; its write names
    that version, and the cancel's write moved it."""
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    running = await orchestrations.start(ctx, a_cleanup())
    in_flight = await orchestrations.get(ctx, running.id)
    ended = await orchestrations.cancel(ctx, running.id, "no longer needed")
    with pytest.raises(PreconditionFailed):
        await world.managers.tasks.cleanup.step_cleanup(ctx, in_flight)
    with pytest.raises(PreconditionFailed):
        await orchestrations.fail(ctx, in_flight, FailReason.DEFECT)
    after = await orchestrations.get(ctx, running.id)
    assert after == ended
    assert (after.status, after.cursor) == (OrchestrationStatus.CANCELLED, 0)


async def test_no_wake_revives_a_cancelled_record(world: World) -> None:
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    by_id = await parked_record(world, ctx, ParkReason.LEASABLE_RESOURCE)
    in_batch = await parked_record(world, ctx)
    ended = {
        record.id: await orchestrations.cancel(ctx, record.id, "gave up")
        for record in (by_id, in_batch)
    }
    assert await orchestrations.wake(ctx, ParkReason.LEASABLE_RESOURCE, by_id.id) == 0
    assert await orchestrations.wake(ctx, ParkReason.PLAN_LIMIT) == 0
    for record_id in ended:
        with pytest.raises(ValidationFailed):
            await orchestrations.resume(ctx, record_id)
        assert await orchestrations.get(ctx, record_id) == ended[record_id]


async def test_a_cancel_takes_the_permission_a_resume_takes(world: World) -> None:
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    parked = await parked_record(world, ctx)
    viewer = build_context(
        RequestContext(request_id=new_id(), app=APP),
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        role=Role.VIEWER,
        permissions=ROLE_PERMISSIONS[Role.VIEWER],
        credential_kind=CredentialKind.AUTH_SESSION_TOKEN,
    )
    with pytest.raises(NotAuthorized):
        await orchestrations.resume(viewer, parked.id)
    with pytest.raises(NotAuthorized):
        await orchestrations.cancel(viewer, parked.id, "not mine to end")
    assert await orchestrations.get(ctx, parked.id) == parked


async def test_a_cancelled_record_goes_with_the_purge_of_settled_records(world: World) -> None:
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    ended = await orchestrations.cancel(ctx, (await parked_record(world, ctx)).id, "done with it")
    assert await orchestrations.purge_across_tenants() == 0, "kept through its retention"
    aged = ended.model_copy(
        update={"updated_at": utcnow() - timedelta(days=31), "version": ended.version + 1}
    )
    await world.storage.get_orchestrations_storage().write_orchestration(
        ctx.org_id, aged, ended.version, ()
    )
    assert await orchestrations.purge_across_tenants() == 1
    with pytest.raises(NotFound):
        await orchestrations.get(ctx, ended.id)


async def test_a_cancel_publishes_the_records_event_at_the_cancelled_version(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The record's own hint names the version the cancel wrote, and a client
    that reads the record at it reads `cancelled`. No step is asked for."""
    ctx = await world.org()
    orchestrations = world.managers.orchestrations
    parked = await parked_record(world, ctx)
    storage = world.storage.get_orchestrations_storage()
    written: list[OutboxRow] = []
    write = storage.write_orchestration

    async def writes(
        org_id: UUID, record: Orchestration, expected: int, rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        written.extend(rows)
        await write(org_id, record, expected, rows)

    monkeypatch.setattr(storage, "write_orchestration", writes)
    ended = await orchestrations.cancel(ctx, parked.id, "stop")
    assert [(row.kind, row.target_id, dict(row.payload)) for row in written] == [
        (UPDATED, parked.id, {"version": ended.version})
    ]
    read = await orchestrations.get(ctx, written[0].target_id)
    assert (read.version, read.status) == (ended.version, OrchestrationStatus.CANCELLED)
