import asyncio
from datetime import timedelta
from uuid import UUID

import pytest

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import DuplicateWorkItem, TenantMismatch
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

SWEEPER = new_id()
LEASE = timedelta(seconds=30)


def make_item(*, lane: str = "default", available_in: timedelta = timedelta(0)) -> WorkItem:
    now = utcnow()
    return WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        updated_by=new_id(),
        kind=WorkKind.NOOP,
        target_id=new_id(),
        idempotency_key=new_id(),
        payload={},
        lane=lane,
        available_at=now + available_in,
    )


class WorkStorageContract:
    @pytest.fixture
    def storage(self) -> WorkStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    @pytest.fixture
    def lane(self) -> str:
        return f"q-{new_id().hex[-12:]}"  # the random tail; the head is the millisecond

    async def test_claim_is_exclusive_and_stamps_the_lease(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org: UUID = new_id()
        item = make_item(lane=lane)
        await storage.create_item(org, item)
        first = await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE)
        assert first is not None
        claimed_org, claimed = first
        assert claimed_org == org
        assert claimed.status is WorkStatus.CLAIMED
        assert claimed.claimed_by == "w1"
        assert claimed.claim_token is not None
        assert claimed.attempts == 1
        assert claimed.lease_expires_at is not None and claimed.lease_expires_at > utcnow()
        assert claimed.payload == {}
        assert await storage.claim_next(lane, [WorkKind.NOOP], "w2", LEASE) is None
        assert await storage.read_item(org, item.id) == claimed

    async def test_a_raced_claim_admits_exactly_one(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        # Two workers claim the one available item at the same moment. The
        # claim is one statement, so exactly one of them holds the item
        # afterwards, and the row names that worker with one attempt spent.
        org = new_id()
        item = make_item(lane=lane)
        await storage.create_item(org, item)
        outcomes = await asyncio.gather(
            storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE),
            storage.claim_next(lane, [WorkKind.NOOP], "w2", LEASE),
        )
        winners = [claimed for claimed in outcomes if claimed is not None]
        assert len(winners) == 1
        claimed_org, claimed = winners[0]
        assert claimed_org == org and claimed.id == item.id
        assert claimed.claimed_by in ("w1", "w2") and claimed.attempts == 1
        assert claimed.claim_token is not None
        assert await storage.read_item(org, item.id) == claimed

    async def test_claim_takes_the_oldest_available_in_its_queue(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org = new_id()
        later = make_item(lane=lane, available_in=timedelta(hours=1))
        elsewhere = make_item(lane=lane + "-other")
        first, second = make_item(lane=lane), make_item(lane=lane)
        for item in (later, elsewhere, second, first):
            await storage.create_item(org, item)
        claimed = await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None and claimed[1].id == min(first.id, second.id)
        claimed = await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None and claimed[1].id == max(first.id, second.id)
        assert await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE) is None

    async def test_requeue_stale_is_per_tenant_conditional_and_staggered(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org_a, org_b = new_id(), new_id()
        stale = [make_item(lane=lane) for _ in range(3)]
        stale[1] = stale[1].model_copy(update={"max_attempts": 1})
        for item in stale:
            await storage.create_item(org_a, item)
        elsewhere = make_item(lane=lane)
        await storage.create_item(org_b, elsewhere)
        expired = timedelta(seconds=-1)
        for _ in range(4):
            assert await storage.claim_next(lane, [WorkKind.NOOP], "w1", expired) is not None
        live = make_item(lane=lane)
        await storage.create_item(org_a, live)
        assert await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE) is not None

        now = utcnow()
        stagger = timedelta(seconds=5)
        changed = await storage.requeue_stale(org_a, now, stagger, SWEEPER)
        assert [item.id for item in changed] == sorted(item.id for item in stale)
        for position, item in enumerate(changed):
            assert item.claimed_by is None and item.lease_expires_at is None
            assert item.claim_token is None
            assert item.last_error == "lease expired" and item.updated_at == now
            assert item.updated_by == SWEEPER
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
        assert await storage.requeue_stale(org_a, utcnow(), stagger, SWEEPER) == []

    async def test_write_if_held_is_conditional_on_the_claim_token(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org, other_org = new_id(), new_id()
        await storage.create_item(org, make_item(lane=lane))
        claimed = await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None
        held = claimed[1]
        assert held.claim_token is not None
        done = held.model_copy(
            update={
                "status": WorkStatus.DONE,
                "claimed_by": None,
                "claim_token": None,
                "lease_expires_at": None,
            }
        )
        assert await storage.write_item_if_held(org, new_id(), done) is None
        assert await storage.write_item_if_held(other_org, held.claim_token, done) is None
        assert await storage.read_item(org, held.id) == held
        assert await storage.write_item_if_held(org, held.claim_token, done) == done
        assert await storage.read_item(org, held.id) == done
        assert await storage.write_item_if_held(org, held.claim_token, done) is None

    async def test_a_re_claim_after_a_requeue_mints_a_new_token(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        # The same worker holds the same item twice: its lease expired, the
        # sweep handed the item back, and it claimed the item again. The first
        # claim's copy carries the old token and cannot settle the second claim.
        org = new_id()
        await storage.create_item(org, make_item(lane=lane))
        first = await storage.claim_next(lane, [WorkKind.NOOP], "w1", timedelta(seconds=-1))
        assert first is not None
        stale = first[1]
        assert stale.claim_token is not None
        assert len(await storage.requeue_stale(org, utcnow(), timedelta(0), SWEEPER)) == 1
        second = await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE)
        assert second is not None
        fresh = second[1]
        assert fresh.claimed_by == stale.claimed_by == "w1"
        assert fresh.claim_token is not None and fresh.claim_token != stale.claim_token
        stale_done = stale.model_copy(update={"status": WorkStatus.DONE, "claim_token": None})
        assert await storage.write_item_if_held(org, stale.claim_token, stale_done) is None
        assert await storage.read_item(org, fresh.id) == fresh
        fresh_done = fresh.model_copy(update={"status": WorkStatus.DONE, "claim_token": None})
        assert await storage.write_item_if_held(org, fresh.claim_token, fresh_done) == fresh_done

    async def test_create_reports_an_existing_id_and_changes_nothing(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        # The create primitive: a second create on the same id is a retry, and
        # a retry neither overwrites the row nor resets the claim on it.
        org = new_id()
        item = make_item(lane=lane)
        assert await storage.create_item(org, item)
        claimed = await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None
        assert not await storage.create_item(org, item.model_copy(update={"last_error": "again"}))
        assert await storage.read_item(org, item.id) == claimed[1]

    async def test_idempotency_key_is_unique(self, storage: WorkStorageInterface) -> None:
        org = new_id()
        item = make_item()
        assert await storage.create_item(org, item)
        duplicate = make_item().model_copy(update={"idempotency_key": item.idempotency_key})
        with pytest.raises(DuplicateWorkItem):
            await storage.create_item(org, duplicate)
        assert await storage.read_item(org, duplicate.id) is None
        assert await storage.read_item(org, item.id) == item

    async def test_reads_and_writes_are_tenant_scoped(self, storage: WorkStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        item = make_item()
        await storage.create_item(org_a, item)
        assert await storage.read_item(org_b, item.id) is None
        with pytest.raises(TenantMismatch):
            await storage.create_item(org_b, item)
        assert await storage.read_item(org_a, item.id) == item
