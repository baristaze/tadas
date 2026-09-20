import pytest
from contracts.tenancy_storage import TenancyStorageContract

from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.storage.impl.memory import IdempotencyStorageMemoryImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl


class TestTenancyStorageMemory(TenancyStorageContract):
    @pytest.fixture
    def markers(self) -> IdempotencyStorageInterface:
        return IdempotencyStorageMemoryImpl()

    @pytest.fixture
    def storage(self, markers: IdempotencyStorageInterface) -> TenancyStorageInterface:
        # The root wires the same two stores into the tenancy impl; the memory
        # twin of the outbox row landing in the commit and the marker being
        # read in the statement.
        assert isinstance(markers, IdempotencyStorageMemoryImpl)
        return TenancyStorageMemoryImpl(OutboxStorageMemoryImpl(), markers)
