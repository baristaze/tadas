from datetime import timedelta
from uuid import UUID

import pytest

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import DuplicateWorkItem, TenantMismatch
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

LEASE = timedelta(seconds=30)


def make_item(*, queue: str = "default", available_in: timedelta = timedelta(0)) -> WorkItem:
    now = utcnow()
    return WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        kind=WorkKind.NOOP,
        target_id=new_id(),
        idempotency_key=new_id(),
        payload={"note": "contract"},
        queue=queue,
        available_at=now + available_in,
    )


class WorkStorageContract:
    @pytest.fixture
    def storage(self) -> WorkStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    @pytest.fixture
    def queue(self) -> str:
        return f"q-{new_id().hex[-12:]}"  # the random tail; the head is the millisecond

    async def test_claim_is_exclusive_and_stamps_the_lease(
        self, storage: WorkStorageInterface, queue: str
    ) -> None:
        org: UUID = new_id()
        item = make_item(queue=queue)
        await storage.write_item(org, item)
        first = await storage.claim_next(queue, [WorkKind.NOOP], "w1", LEASE)
        assert first is not None
        claimed_org, claimed = first
        assert claimed_org == org
        assert claimed.status is WorkStatus.CLAIMED
        assert claimed.claimed_by == "w1"
        assert claimed.attempts == 1
        assert claimed.lease_expires_at is not None and claimed.lease_expires_at > utcnow()
        assert claimed.payload == {"note": "contract"}
        assert await storage.claim_next(queue, [WorkKind.NOOP], "w2", LEASE) is None
        assert await storage.read_item(org, item.id) == claimed

    async def test_claim_takes_the_oldest_available_in_its_queue(
        self, storage: WorkStorageInterface, queue: str
    ) -> None:
        org = new_id()
        later = make_item(queue=queue, available_in=timedelta(hours=1))
        elsewhere = make_item(queue=queue + "-other")
        first, second = make_item(queue=queue), make_item(queue=queue)
        for item in (later, elsewhere, second, first):
            await storage.write_item(org, item)
        claimed = await storage.claim_next(queue, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None and claimed[1].id == min(first.id, second.id)
        claimed = await storage.claim_next(queue, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None and claimed[1].id == max(first.id, second.id)
        assert await storage.claim_next(queue, [WorkKind.NOOP], "w1", LEASE) is None

    async def test_requeue_stale_is_per_tenant_conditional_and_staggered(
        self, storage: WorkStorageInterface, queue: str
    ) -> None:
        org_a, org_b = new_id(), new_id()
        stale = [make_item(queue=queue) for _ in range(3)]
        stale[1] = stale[1].model_copy(update={"max_attempts": 1})
        for item in stale:
            await storage.write_item(org_a, item)
        elsewhere = make_item(queue=queue)
        await storage.write_item(org_b, elsewhere)
        expired = timedelta(seconds=-1)
        for _ in range(4):
            assert await storage.claim_next(queue, [WorkKind.NOOP], "w1", expired) is not None
        live = make_item(queue=queue)
        await storage.write_item(org_a, live)
        assert await storage.claim_next(queue, [WorkKind.NOOP], "w1", LEASE) is not None

        now = utcnow()
        stagger = timedelta(seconds=5)
        changed = await storage.requeue_stale(org_a, now, stagger)
        assert [item.id for item in changed] == sorted(item.id for item in stale)
        for position, item in enumerate(changed):
            assert item.claimed_by is None and item.lease_expires_at is None
            assert item.last_error == "lease expired" and item.updated_at == now
            if item.max_attempts == 1:
                assert item.status is WorkStatus.FAILED
            else:
                assert item.status is WorkStatus.QUEUED
                assert item.available_at == now + stagger * position
            assert await storage.read_item(org_a, item.id) == item
        held = await storage.read_item(org_a, live.id)
        assert held is not None and held.status is WorkStatus.CLAIMED
        other = await storage.read_item(org_b, elsewhere.id)
        assert other is not None and other.status is WorkStatus.CLAIMED
        assert await storage.requeue_stale(org_a, utcnow(), stagger) == []

    async def test_write_if_held_refuses_a_row_this_worker_does_not_hold(
        self, storage: WorkStorageInterface, queue: str
    ) -> None:
        org, other_org = new_id(), new_id()
        await storage.write_item(org, make_item(queue=queue))
        claimed = await storage.claim_next(queue, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None
        held = claimed[1]
        done = held.model_copy(
            update={"status": WorkStatus.DONE, "claimed_by": None, "lease_expires_at": None}
        )
        assert await storage.write_item_if_held(org, "w2", done) is None
        assert await storage.write_item_if_held(other_org, "w1", done) is None
        assert await storage.read_item(org, held.id) == held
        assert await storage.write_item_if_held(org, "w1", done) == done
        assert await storage.read_item(org, held.id) == done
        assert await storage.write_item_if_held(org, "w1", done) is None

    async def test_idempotency_key_is_unique(self, storage: WorkStorageInterface) -> None:
        org = new_id()
        item = make_item()
        await storage.write_item(org, item)
        duplicate = make_item().model_copy(update={"idempotency_key": item.idempotency_key})
        with pytest.raises(DuplicateWorkItem):
            await storage.write_item(org, duplicate)
        await storage.write_item(org, item.model_copy(update={"last_error": "same row"}))

    async def test_reads_and_writes_are_tenant_scoped(self, storage: WorkStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        item = make_item()
        await storage.write_item(org_a, item)
        assert await storage.read_item(org_b, item.id) is None
        with pytest.raises(TenantMismatch):
            await storage.write_item(org_b, item)
