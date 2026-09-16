from uuid import UUID

import pytest

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import DuplicateIdempotencyKey, TenantMismatch
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.types.record import IdempotencyRecord


def make_record(user_id: UUID | None = None, key: str = "req-1") -> IdempotencyRecord:
    return IdempotencyRecord(
        id=new_id(),
        user_id=user_id or new_id(),
        key=key,
        request_digest="sha256:abc",
        created_at=utcnow(),
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
