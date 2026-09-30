import pytest
from contracts.idempotency_storage import IdempotencyStorageContract

from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.storage.impl.memory import IdempotencyStorageMemoryImpl


class TestIdempotencyStorageMemory(IdempotencyStorageContract):
    @pytest.fixture
    def storage(self) -> IdempotencyStorageInterface:
        return IdempotencyStorageMemoryImpl()
