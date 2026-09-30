import pytest
from contracts.outbox_storage import OutboxStorageContract

from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl


class TestOutboxStorageMemory(OutboxStorageContract):
    @pytest.fixture
    def outbox(self) -> OutboxStorageInterface:
        return OutboxStorageMemoryImpl()

    @pytest.fixture
    def tenancy(self, outbox: OutboxStorageMemoryImpl) -> TenancyStorageInterface:
        return TenancyStorageMemoryImpl(outbox)
