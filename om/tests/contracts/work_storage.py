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
        return f"q-{new_id().hex[:8]}"

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

    async def test_read_stale_crosses_tenants_and_returns_them(
        self, storage: WorkStorageInterface, queue: str
    ) -> None:
        org_a, org_b = new_id(), new_id()
        await storage.write_item(org_a, make_item(queue=queue))
        await storage.write_item(org_b, make_item(queue=queue))
        expired = timedelta(seconds=-1)
        one = await storage.claim_next(queue, [WorkKind.NOOP], "w1", expired)
        two = await storage.claim_next(queue, [WorkKind.NOOP], "w1", expired)
        assert one is not None and two is not None
        stale = await storage.read_stale(utcnow())
        assert {org for org, _ in stale} >= {org_a, org_b}
        assert {item.id for _, item in stale} >= {one[1].id, two[1].id}

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
