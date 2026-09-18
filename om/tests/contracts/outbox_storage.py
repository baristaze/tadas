"""The outbox contract, exercised through a core-role write: the row lands
with the task it belongs to, the sweep reads it across tenants, the relay
marks it done, and the purge deletes what is done."""

from datetime import timedelta
from uuid import UUID

import pytest

from contracts.task_storage import make_task
from tadas.om.base import new_id, utcnow
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.tasks.storage import TasksStorageInterface


def make_row(target_id: UUID) -> OutboxRow:
    return OutboxRow(
        id=new_id(),
        created_at=utcnow(),
        kind="tasks.task.created",
        target_id=target_id,
        payload={"title": "t"},
        actor_id=new_id(),
        request_id=new_id(),
    )


class OutboxStorageContract:
    @pytest.fixture
    def tasks(self) -> TasksStorageInterface:
        raise NotImplementedError("the concrete test class provides the tasks storage")

    @pytest.fixture
    def outbox(self) -> OutboxStorageInterface:
        raise NotImplementedError("the concrete test class provides the outbox storage")

    async def test_the_row_lands_with_the_core_row_and_is_swept_across_tenants(
        self, tasks: TasksStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        first, second = make_task(), make_task()
        row_a, row_b = make_row(first.id), make_row(second.id)
        await tasks.write_task(org_a, first, row_a)
        await tasks.write_task(org_b, second, row_b)
        await tasks.write_task(org_a, make_task())  # no handoff, no row
        pending = await outbox.read_pending(10)
        mine = [(org, row) for org, row in pending if row.id in (row_a.id, row_b.id)]
        assert mine == [(org_a, row_a), (org_b, row_b)]
        assert [row.payload for _, row in mine] == [{"title": "t"}, {"title": "t"}]
        assert (await tasks.read_task(org_a, first.id)) == first

    async def test_mark_done_is_per_tenant_and_idempotent(
        self, tasks: TasksStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        org = new_id()
        task = make_task()
        row = make_row(task.id)
        await tasks.write_task(org, task, row)
        await outbox.mark_done(new_id(), row.id)  # another tenant: no effect
        assert row.id in {r.id for _, r in await outbox.read_pending(100)}
        await outbox.mark_done(org, row.id)
        await outbox.mark_done(org, row.id)
        assert row.id not in {r.id for _, r in await outbox.read_pending(100)}

    async def test_purge_deletes_only_rows_done_before_the_cut(
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
        assert pending_row.id in {r.id for _, r in await outbox.read_pending(100)}
