"""The work storage contract. The cases named in `CROSS_TENANT_CASES` are the
tenant fence's evidence: each one presents another tenant's identifier and
asserts that nothing is found and nothing changes. The negative control that
says what they catch is in `docs/runbooks/tenant-isolation.md`."""

from datetime import timedelta
from uuid import UUID

import pytest

from contracts.racing import race
from tadas.om.base import EMPTY_UUID, new_id, utcnow
from tadas.om.exceptions import TenantMismatch
from tadas.om.work.storage import InsertOutcome, WorkStorageInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

LEASE = timedelta(seconds=30)

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_item",
        "read_item",
        "read_item_by_key",
        "requeue_stale",
        "write_item_if_failed",
        "write_item_if_held",
    }
)
"""Every method of `WorkStorageInterface` that takes a tenant has a case in
this module that presents another tenant's. `test_storage_exceptions.py` holds
the two sets to each other, so a new method arrives with its case."""


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
        request_id=new_id(),
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
        assert claimed.created_by == item.created_by, "the person who asked for the work"
        assert claimed.updated_by == EMPTY_UUID, "the claim is the platform's write"
        assert claimed.lease_expires_at is not None and claimed.lease_expires_at > utcnow()
        assert claimed.payload == {}
        assert await storage.claim_next(lane, [WorkKind.NOOP], "w2", LEASE) is None
        assert await storage.read_item(org, item.id) == claimed

    async def test_two_claims_admit_exactly_one(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        # Two workers reach for the one available item. The claim is one
        # statement, so exactly one of them holds the item afterwards, and the
        # row names that worker with one attempt spent. See contracts/racing.py
        # for what each impl's run of this proves.
        org = new_id()
        item = make_item(lane=lane)
        await storage.create_item(org, item)
        run = await race(
            storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE),
            storage.claim_next(lane, [WorkKind.NOOP], "w2", LEASE),
        )
        assert len(run.admitted) == 1, run.summary()
        winner = run.admitted[0]
        assert winner is not None
        claimed_org, claimed = winner
        assert claimed_org == org and claimed.id == item.id
        assert claimed.claimed_by in ("w1", "w2") and claimed.attempts == 1
        assert claimed.claim_token is not None
        assert await storage.read_item(org, item.id) == claimed
        # The refusal the claim gives whoever arrives after it: the item is
        # held, so a third worker finds nothing and the row is untouched.
        assert await storage.claim_next(lane, [WorkKind.NOOP], "w3", LEASE) is None
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
        changed = await storage.requeue_stale(org_a, now, stagger, limit=10)
        assert [item.id for item in changed] == sorted(item.id for item in stale)
        for position, item in enumerate(changed):
            assert item.claimed_by is None and item.lease_expires_at is None
            assert item.claim_token is None
            assert item.last_error == "lease expired" and item.updated_at == now
            assert item.updated_by == EMPTY_UUID, "the requeue is the platform's write"
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
        assert await storage.requeue_stale(org_a, utcnow(), stagger, limit=10) == []

    async def test_requeue_stale_takes_a_batch_and_leaves_the_rest_for_the_next(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        # The bound is in the statement: the first `limit` stale items by id
        # move, staggered from zero, and the next call moves the rest.
        org = new_id()
        items = [make_item(lane=lane) for _ in range(5)]
        for item in items:
            await storage.create_item(org, item)
        for _ in items:
            expired = timedelta(seconds=-1)
            assert await storage.claim_next(lane, [WorkKind.NOOP], "w1", expired) is not None
        ids = sorted(item.id for item in items)
        now = utcnow()
        stagger = timedelta(seconds=5)
        first = await storage.requeue_stale(org, now, stagger, limit=2)
        assert [item.id for item in first] == ids[:2]
        assert [item.available_at for item in first] == [now, now + stagger]
        for item_id in ids[2:]:
            left = await storage.read_item(org, item_id)
            assert left is not None and left.status is WorkStatus.CLAIMED
        rest = await storage.requeue_stale(org, now, stagger, limit=10)
        assert [item.id for item in rest] == ids[2:]
        assert [item.available_at for item in rest] == [now + stagger * i for i in range(3)]
        assert await storage.requeue_stale(org, now, stagger, limit=10) == []

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

    async def test_write_if_failed_is_conditional_on_the_item_being_failed(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org, other_org = new_id(), new_id()
        item = make_item(lane=lane)
        await storage.create_item(org, item)
        requeued = item.model_copy(update={"attempts": 0, "updated_by": new_id()})
        assert await storage.write_item_if_failed(org, requeued) is None, "queued, not failed"
        claimed = await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None and claimed[1].claim_token is not None
        failed = claimed[1].model_copy(
            update={
                "status": WorkStatus.FAILED,
                "claimed_by": None,
                "claim_token": None,
                "lease_expires_at": None,
                "last_error": "refused",
            }
        )
        assert await storage.write_item_if_held(org, claimed[1].claim_token, failed) == failed
        back = failed.model_copy(update={"status": WorkStatus.QUEUED, "attempts": 0})
        assert await storage.write_item_if_failed(other_org, back) is None
        assert await storage.read_item(org, item.id) == failed
        assert await storage.write_item_if_failed(org, back) == back
        assert await storage.read_item(org, item.id) == back
        assert await storage.write_item_if_failed(org, back) is None, "moved once"
        assert await storage.write_item_if_failed(org, make_item(lane=lane)) is None, "unknown"

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
        assert len(await storage.requeue_stale(org, utcnow(), timedelta(0), limit=10)) == 1
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
        assert await storage.create_item(org, item) is InsertOutcome.INSERTED
        claimed = await storage.claim_next(lane, [WorkKind.NOOP], "w1", LEASE)
        assert claimed is not None
        again = item.model_copy(update={"last_error": "again"})
        assert await storage.create_item(org, again) is InsertOutcome.ID_EXISTS
        assert await storage.read_item(org, item.id) == claimed[1]

    async def test_a_taken_idempotency_key_is_reported_and_changes_nothing(
        self, storage: WorkStorageInterface
    ) -> None:
        # The key is the producer's, so a second insert under it is a retry, not
        # an error: the create reports which key collided, nothing changes, and
        # the row it names reads back by the key, under another id than the
        # one presented. That is what lets the relay run twice.
        org = new_id()
        item = make_item()
        assert await storage.create_item(org, item) is InsertOutcome.INSERTED
        duplicate = make_item().model_copy(update={"idempotency_key": item.idempotency_key})
        assert await storage.create_item(org, duplicate) is InsertOutcome.KEY_EXISTS
        assert await storage.read_item(org, duplicate.id) is None
        assert await storage.read_item(org, item.id) == item
        assert await storage.read_item_by_key(org, item.idempotency_key) == item
        assert await storage.read_item_by_key(new_id(), item.idempotency_key) is None
        assert await storage.read_item_by_key(org, new_id()) is None

    async def test_a_key_is_taken_in_its_tenant_and_free_in_every_other(
        self, storage: WorkStorageInterface
    ) -> None:
        # The key is unique within its tenant and nowhere else: one tenant's
        # producer never takes a key out of another's, and each reads its own
        # row back under it.
        org, elsewhere = new_id(), new_id()
        mine = make_item()
        theirs = make_item().model_copy(update={"idempotency_key": mine.idempotency_key})
        assert await storage.create_item(org, mine) is InsertOutcome.INSERTED
        assert await storage.create_item(elsewhere, theirs) is InsertOutcome.INSERTED
        assert await storage.read_item_by_key(org, mine.idempotency_key) == mine
        assert await storage.read_item_by_key(elsewhere, mine.idempotency_key) == theirs

    async def test_reads_and_writes_are_tenant_scoped(self, storage: WorkStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        item = make_item()
        await storage.create_item(org_a, item)
        assert await storage.read_item(org_b, item.id) is None
        with pytest.raises(TenantMismatch):
            await storage.create_item(org_b, item)
        assert await storage.read_item(org_a, item.id) == item

    async def test_a_backlog_past_a_batch_goes_a_batch_at_a_time(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org = new_id()
        settled = {
            "status": WorkStatus.DONE,
            "updated_at": utcnow() - timedelta(days=2),
            "claim_token": None,
            "claimed_by": None,
            "lease_expires_at": None,
        }
        for _ in range(3):
            await storage.create_item(org, make_item(lane=lane).model_copy(update=settled))
        cut = utcnow() - timedelta(days=1)
        assert await storage.purge_items(cut, 2) == 2
        assert await storage.purge_items(cut, 2) == 1
        assert await storage.purge_items(cut, 2) == 0

    async def test_purge_items_counts_done_and_failed_past_the_cut_in_every_tenant(
        self, storage: WorkStorageInterface, lane: str
    ) -> None:
        org, other_org = new_id(), new_id()
        long_ago = utcnow() - timedelta(days=2)
        old = {
            "updated_at": long_ago,
            "claim_token": None,
            "claimed_by": None,
            "lease_expires_at": None,
        }
        old_done = make_item(lane=lane).model_copy(update={**old, "status": WorkStatus.DONE})
        old_failed = make_item(lane=lane).model_copy(update={**old, "status": WorkStatus.FAILED})
        old_queued = make_item(lane=lane).model_copy(update={**old, "status": WorkStatus.QUEUED})
        fresh_done = make_item(lane=lane).model_copy(update={"status": WorkStatus.DONE})
        elsewhere = make_item(lane=lane).model_copy(update={**old, "status": WorkStatus.DONE})
        for item in (old_done, old_failed, old_queued, fresh_done):
            await storage.create_item(org, item)
        await storage.create_item(other_org, elsewhere)
        # The purge is the sweep's, across tenants: another suite's settled
        # items may be in the same table, so the count is at least these three.
        assert await storage.purge_items(utcnow() - timedelta(days=1), 1000) >= 3
        assert await storage.read_item(org, old_done.id) is None
        assert await storage.read_item(org, old_failed.id) is None
        assert await storage.read_item(org, old_queued.id) == old_queued
        assert await storage.read_item(org, fresh_done.id) == fresh_done
        assert await storage.read_item(other_org, elsewhere.id) is None
        assert await storage.purge_items(utcnow() - timedelta(days=1), 1000) == 0
