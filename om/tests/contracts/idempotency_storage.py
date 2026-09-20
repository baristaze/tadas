import asyncio
from datetime import datetime, timedelta
from uuid import UUID

import pytest

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import DuplicateIdempotencyKey, TenantMismatch
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.types.record import IdempotencyRecord


def make_record(
    user_id: UUID | None = None, key: str = "req-1", created_at: datetime | None = None
) -> IdempotencyRecord:
    return IdempotencyRecord(
        id=new_id(),
        user_id=user_id or new_id(),
        key=key,
        request_digest="sha256:abc",
        target_id=new_id(),
        attempt_id=new_id(),
        created_at=created_at or utcnow(),
    )


class IdempotencyStorageContract:
    @pytest.fixture
    def storage(self) -> IdempotencyStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_round_trip_is_user_scoped_within_the_tenant(
        self, storage: IdempotencyStorageInterface
    ) -> None:
        org, other_org = new_id(), new_id()
        record = make_record()
        await storage.write_record(org, record)
        assert await storage.read_record(org, record.user_id, record.key) == record
        assert await storage.read_record(org, new_id(), record.key) is None
        assert await storage.read_record(org, record.user_id, "other") is None
        assert await storage.read_record(other_org, record.user_id, record.key) is None
        finished = record.model_copy(update={"status": 201, "body": '{"id":"x"}'})
        await storage.write_record(org, finished)
        assert await storage.read_record(org, record.user_id, record.key) == finished
        assert not finished.pending and record.pending

    async def test_key_is_unique_per_tenant_and_user(
        self, storage: IdempotencyStorageInterface
    ) -> None:
        org = new_id()
        record = make_record()
        await storage.write_record(org, record)
        with pytest.raises(DuplicateIdempotencyKey):
            await storage.write_record(org, make_record(record.user_id, record.key))
        await storage.write_record(org, make_record(new_id(), record.key))
        await storage.write_record(new_id(), make_record(record.user_id, record.key))
        assert await storage.read_record(org, record.user_id, record.key) == record

    async def test_write_refuses_another_tenant(self, storage: IdempotencyStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        record = make_record()
        await storage.write_record(org_a, record)
        with pytest.raises(TenantMismatch):
            await storage.write_record(org_b, record.model_copy(update={"status": 200}))
        assert await storage.read_record(org_a, record.user_id, record.key) == record

    async def test_finish_is_conditional_on_the_attempt(
        self, storage: IdempotencyStorageInterface
    ) -> None:
        org = new_id()
        record = make_record()
        await storage.write_record(org, record)

        async def finish(org_id: UUID, attempt_id: UUID, body: str) -> IdempotencyRecord | None:
            return await storage.finish_pending(
                org_id, record.user_id, record.key, attempt_id, 201, body
            )

        # A stale attempt (one that lost the marker) and another tenant change nothing.
        assert await finish(org, new_id(), "stale") is None
        assert await finish(new_id(), record.attempt_id, "elsewhere") is None
        assert await storage.read_record(org, record.user_id, record.key) == record
        # The holder finishes it once; the outcome is then nobody's to rewrite.
        finished = await finish(org, record.attempt_id, '{"id":"x"}')
        assert finished is not None and finished.status == 201 and finished.body == '{"id":"x"}'
        assert finished.attempt_id == record.attempt_id
        assert await storage.read_record(org, record.user_id, record.key) == finished
        assert await finish(org, record.attempt_id, "again") is None
        assert await storage.read_record(org, record.user_id, record.key) == finished

    async def test_release_is_conditional_on_the_attempt_and_keeps_a_finished_record(
        self, storage: IdempotencyStorageInterface
    ) -> None:
        org_id, user_id = new_id(), new_id()
        pending = make_record(user_id, "k-pending")
        await storage.write_record(org_id, pending)

        async def release(org: UUID, key: str, attempt_id: UUID) -> bool:
            return await storage.release_pending(org, user_id, key, attempt_id)

        # A stale attempt and another tenant release nothing.
        assert not await release(org_id, "k-pending", new_id())
        assert not await release(new_id(), "k-pending", pending.attempt_id)
        assert await storage.read_record(org_id, user_id, "k-pending") == pending
        assert await release(org_id, "k-pending", pending.attempt_id)
        assert await storage.read_record(org_id, user_id, "k-pending") is None
        assert not await release(org_id, "k-pending", pending.attempt_id)
        finished = make_record(user_id, "k-done").model_copy(update={"status": 201, "body": "{}"})
        await storage.write_record(org_id, finished)
        assert not await release(org_id, "k-done", finished.attempt_id)
        assert await storage.read_record(org_id, user_id, "k-done") == finished

    async def test_take_over_is_one_conditional_write(
        self, storage: IdempotencyStorageInterface
    ) -> None:
        org = new_id()
        record = make_record()
        await storage.write_record(org, record)
        later = utcnow() + timedelta(minutes=5)

        async def take_over(
            org_id: UUID, cutoff: datetime, attempt_id: UUID | None = None
        ) -> IdempotencyRecord | None:
            return await storage.take_over_pending(
                org_id, record.user_id, record.key, cutoff, later, attempt_id or new_id()
            )

        # Not abandoned yet: the marker began after the cut-off.
        assert await take_over(org, record.created_at) is None
        # Abandoned: the take-over restarts the lease and stamps its own attempt
        # in the one write, and the same cut-off then matches nothing.
        cutoff = record.created_at + timedelta(seconds=1)
        second_attempt = new_id()
        taken = await take_over(org, cutoff, second_attempt)
        assert taken is not None and taken.created_at == later and taken.pending
        assert taken.attempt_id == second_attempt and taken.target_id == record.target_id
        assert await take_over(org, cutoff) is None
        assert await storage.read_record(org, record.user_id, record.key) == taken
        # The first attempt lost the marker: its finish and its release are refused.
        assert (
            await storage.finish_pending(
                org, record.user_id, record.key, record.attempt_id, 201, "{}"
            )
            is None
        )
        assert not await storage.release_pending(org, record.user_id, record.key, record.attempt_id)
        assert await storage.read_record(org, record.user_id, record.key) == taken
        # A finished record is never taken over, and another tenant's is never matched.
        await storage.write_record(org, taken.model_copy(update={"status": 200, "body": "{}"}))
        assert await take_over(org, later) is None
        assert await take_over(new_id(), later) is None

    async def test_a_raced_take_over_admits_exactly_one(
        self, storage: IdempotencyStorageInterface
    ) -> None:
        # Two retries find the same abandoned marker at the same moment. The
        # take-over is one conditional write, so exactly one of them holds the
        # marker afterwards, and the record names that one's attempt.
        org = new_id()
        record = make_record(created_at=utcnow() - timedelta(minutes=10))
        await storage.write_record(org, record)
        cutoff, restarted_at = utcnow() - timedelta(minutes=2), utcnow()
        attempts = [new_id(), new_id()]
        outcomes = await asyncio.gather(
            *(
                storage.take_over_pending(
                    org, record.user_id, record.key, cutoff, restarted_at, attempt_id
                )
                for attempt_id in attempts
            )
        )
        winners = [taken for taken in outcomes if taken is not None]
        assert len(winners) == 1
        stored = await storage.read_record(org, record.user_id, record.key)
        assert stored is not None and stored == winners[0]
        assert stored.attempt_id in attempts
        assert stored.pending and stored.created_at == restarted_at
