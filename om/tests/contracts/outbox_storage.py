"""The outbox contract, exercised through a core-role write: the row lands
with the task it belongs to, the sweep claims it across tenants one attempt
at a time, the relay marks it done or records the failure, and the purge
deletes what is settled."""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID

import pytest

from contracts.task_storage import make_task
from tadas.om.base import new_id, utcnow
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.tasks.storage import TasksStorageInterface

NO_DELAY = timedelta(0)


def make_row(target_id: UUID, *, age: timedelta = timedelta(minutes=1)) -> OutboxRow:
    return OutboxRow(
        id=new_id(),
        created_at=utcnow() - age,
        kind="tasks.task.created",
        target_id=target_id,
        payload={"title": "t"},
        actor_id=new_id(),
        request_id=new_id(),
        app="portal",
    )


async def claim_all(
    outbox: OutboxStorageInterface,
    *,
    limit: int = 100,
    now: datetime | None = None,
    grace: timedelta = NO_DELAY,
    backoff: timedelta = NO_DELAY,
) -> list[tuple[UUID, OutboxRow]]:
    """A claim with no delay after it, so the same rows are claimable again."""
    return await outbox.claim_pending(limit, now or utcnow(), grace, backoff, backoff)


class OutboxStorageContract:
    @pytest.fixture
    def tasks(self) -> TasksStorageInterface:
        raise NotImplementedError("the concrete test class provides the tasks storage")

    @pytest.fixture
    def outbox(self) -> OutboxStorageInterface:
        raise NotImplementedError("the concrete test class provides the outbox storage")

    async def test_the_row_lands_with_the_core_row_and_is_claimed_across_tenants(
        self, tasks: TasksStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        first, second = make_task(), make_task()
        row_a, row_b = make_row(first.id), make_row(second.id)
        await tasks.write_task(org_a, first, row_a)
        await tasks.write_task(org_b, second, row_b)
        await tasks.write_task(org_a, make_task())  # no handoff, no row
        claimed = await claim_all(outbox)
        mine = [(org, row) for org, row in claimed if row.id in (row_a.id, row_b.id)]
        assert [(org, row.id) for org, row in mine] == [(org_a, row_a.id), (org_b, row_b.id)]
        assert [row.payload for _, row in mine] == [{"title": "t"}, {"title": "t"}]
        assert [row.attempts for _, row in mine] == [1, 1]
        assert (await tasks.read_task(org_a, first.id)) == first

    async def test_a_claim_spends_an_attempt_and_sets_the_next_with_a_growing_delay(
        self, tasks: TasksStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        org = new_id()
        task = make_task()
        row = make_row(task.id)
        await tasks.write_task(org, task, row)
        base, cap = timedelta(seconds=30), timedelta(seconds=100)
        now = utcnow()
        for attempt, delay in enumerate((30, 60, 100, 100), start=1):
            claimed = await outbox.claim_pending(100, now, NO_DELAY, base, cap)
            mine = [r for _, r in claimed if r.id == row.id]
            assert len(mine) == 1
            assert mine[0].attempts == attempt
            assert mine[0].next_attempt_at == now + timedelta(seconds=delay)
            # Not due yet: the same clock claims nothing, a later one does.
            assert row.id not in {r.id for _, r in await claim_all(outbox, now=now)}
            now = now + timedelta(seconds=delay)
        assert row.id in {r.id for _, r in await claim_all(outbox, now=now)}

    async def test_a_poison_row_does_not_block_the_rows_behind_it(
        self, tasks: TasksStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        org = new_id()
        poison, fine = make_task(), make_task()
        poison_row, fine_row = make_row(poison.id), make_row(fine.id)
        await tasks.write_task(org, poison, poison_row)
        await tasks.write_task(org, fine, fine_row)
        claimed = await claim_all(outbox, backoff=timedelta(hours=1))
        assert {r.id for _, r in claimed} >= {poison_row.id, fine_row.id}
        # The poison row's relay failed; the fine one was done. A newer row
        # lands, and the next sweep claims it alone: the poison row waits out
        # its delay and the new row is not behind it.
        await outbox.record_failure(org, poison_row.id, "bus down", None)
        await outbox.mark_done(org, fine_row.id)
        newer = make_task()
        newer_row = make_row(newer.id)
        await tasks.write_task(org, newer, newer_row)
        claimed = await claim_all(outbox)
        ids = {r.id for _, r in claimed}
        assert newer_row.id in ids and poison_row.id not in ids and fine_row.id not in ids
        # Once its delay is out the poison row is claimed again, error kept.
        later = utcnow() + timedelta(hours=2)
        again = [r for _, r in await claim_all(outbox, now=later) if r.id == poison_row.id]
        assert len(again) == 1 and again[0].attempts == 2 and again[0].last_error == "bus down"

    async def test_two_concurrent_sweeps_claim_disjoint_sets(
        self, tasks: TasksStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        org = new_id()
        rows: list[OutboxRow] = []
        for _ in range(4):
            task = make_task()
            row = make_row(task.id)
            await tasks.write_task(org, task, row)
            rows.append(row)
        now = utcnow()
        outcomes = await asyncio.gather(
            outbox.claim_pending(2, now, NO_DELAY, timedelta(hours=1), timedelta(hours=1)),
            outbox.claim_pending(2, now, NO_DELAY, timedelta(hours=1), timedelta(hours=1)),
        )
        first = {r.id for _, r in outcomes[0]}
        second = {r.id for _, r in outcomes[1]}
        assert first and second and not (first & second)
        assert (first | second) >= {row.id for row in rows}

    async def test_a_row_younger_than_the_grace_is_left_to_the_request_path(
        self, tasks: TasksStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        org = new_id()
        young, old = make_task(), make_task()
        young_row = make_row(young.id, age=timedelta(0))
        old_row = make_row(old.id, age=timedelta(minutes=5))
        await tasks.write_task(org, young, young_row)
        await tasks.write_task(org, old, old_row)
        ids = {r.id for _, r in await claim_all(outbox, grace=timedelta(minutes=1))}
        assert old_row.id in ids and young_row.id not in ids
        assert young_row.id in {r.id for _, r in await claim_all(outbox)}

    async def test_mark_done_is_per_tenant_and_idempotent(
        self, tasks: TasksStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        org = new_id()
        task = make_task()
        row = make_row(task.id)
        await tasks.write_task(org, task, row)
        await outbox.mark_done(new_id(), row.id)  # another tenant: no effect
        assert row.id in {r.id for _, r in await claim_all(outbox)}
        await outbox.mark_done(org, row.id)
        await outbox.mark_done(org, row.id)
        assert row.id not in {r.id for _, r in await claim_all(outbox)}

    async def test_a_failed_row_is_a_dead_letter_never_claimed_again(
        self, tasks: TasksStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        org = new_id()
        task = make_task()
        row = make_row(task.id)
        await tasks.write_task(org, task, row)
        await outbox.record_failure(new_id(), row.id, "elsewhere", utcnow())  # another tenant
        assert row.id in {r.id for _, r in await claim_all(outbox)}
        failed_at = utcnow()
        await outbox.record_failure(org, row.id, "for good", failed_at)
        assert row.id not in {r.id for _, r in await claim_all(outbox)}
        # Done rows stay done: a failure recorded afterwards changes nothing.
        done = make_task()
        done_row = make_row(done.id)
        await tasks.write_task(org, done, done_row)
        await outbox.mark_done(org, done_row.id)
        await outbox.record_failure(org, done_row.id, "too late", utcnow())
        # The purge is cross-tenant, so only what it takes of these two rows
        # is asserted: nothing before they settled, both once the cut passes.
        await outbox.purge_done(failed_at - timedelta(seconds=1))
        assert await outbox.purge_done(failed_at + timedelta(seconds=1)) >= 2

    async def test_purge_deletes_only_rows_settled_before_the_cut(
        self, tasks: TasksStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        org = new_id()
        done, pending = make_task(), make_task()
        done_row, pending_row = make_row(done.id), make_row(pending.id)
        await tasks.write_task(org, done, done_row)
        await tasks.write_task(org, pending, pending_row)
        await outbox.mark_done(org, done_row.id)
        assert await outbox.purge_done(utcnow() - timedelta(hours=1)) == 0
        assert await outbox.purge_done(utcnow() + timedelta(seconds=1)) >= 1
        assert pending_row.id in {r.id for _, r in await claim_all(outbox)}
