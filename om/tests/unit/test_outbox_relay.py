"""The sweep's relay: a poison row stops nothing behind it, and a row whose
attempts are spent is a dead letter, failed for good, counted, and named by
an audit event."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.outbox_storage import claim_all, make_row
from contracts.task_storage import make_task

from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.observability import OUTCOMES
from tadas.om.base import new_id, utcnow
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.events.types.event import Event
from tadas.om.outbox.impl.relay import DEAD_LETTER_KIND, OutboxOptions, OutboxRelayImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.tasks.storage.impl.memory import TasksStorageMemoryImpl

NO_GRACE = OutboxOptions(grace=timedelta(0), backoff_base=timedelta(0), max_attempts=2)


class PoisonedEvents(EventStorageMemoryImpl):
    """The append refuses one row's event, as a bad payload downstream would."""

    def __init__(self, poison_id: UUID) -> None:
        super().__init__()
        self.poison_id = poison_id

    async def append(self, org_id: UUID, event: Event) -> Event:
        if event.id == self.poison_id:
            raise RuntimeError("cannot append this one")
        return await super().append(org_id, event)


@pytest.fixture
def infra(tmp_path: Path) -> InfraLocalImpl:
    return InfraLocalImpl(tmp_path)


def dead_letters() -> float:
    return OUTCOMES.labels(subsystem="outbox", outcome="dead_letter")._value.get()


async def test_a_poison_row_does_not_block_the_rows_behind_it_and_dies_after_max_attempts(
    infra: InfraLocalImpl,
) -> None:
    outbox = OutboxStorageMemoryImpl()
    tasks = TasksStorageMemoryImpl(outbox)
    org = new_id()
    poison, fine = make_task(), make_task()
    poison_row, fine_row = make_row(poison.id), make_row(fine.id)
    await tasks.create_task(org, poison, poison_row)
    await tasks.create_task(org, fine, fine_row)
    events = PoisonedEvents(poison_row.id)
    relay = OutboxRelayImpl(outbox, events, infra.get_topics(), NO_GRACE)
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
    row = make_row(task.id, age=timedelta(0))
    await tasks.create_task(org, task, row)
    relay = OutboxRelayImpl(outbox, EventStorageMemoryImpl(), infra.get_topics())
    assert await relay.relay_pending(10) == 0, "the request path relays a fresh row"
    assert await relay.relay(org, row)
    assert await claim_all(outbox) == []


async def test_purge_takes_done_and_failed_rows_past_the_retention(infra: InfraLocalImpl) -> None:
    outbox = OutboxStorageMemoryImpl()
    tasks = TasksStorageMemoryImpl(outbox)
    org = new_id()
    done, failed = make_task(), make_task()
    done_row, failed_row = make_row(done.id), make_row(failed.id)
    await tasks.create_task(org, done, done_row)
    await tasks.create_task(org, failed, failed_row)
    await outbox.mark_done(org, done_row.id)
    await outbox.record_failure(org, failed_row.id, "for good", utcnow())
    relay = OutboxRelayImpl(outbox, EventStorageMemoryImpl(), infra.get_topics())
    assert await relay.purge_done(timedelta(hours=1)) == 0
    assert await relay.purge_done(timedelta(seconds=-1)) == 2
