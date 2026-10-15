import pytest

from tadas.om.billing.storage import BillingStorageInterface
from tadas.om.billing.storage.impl.memory import BillingStorageMemoryImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl

from contracts.billing_storage import BillingStorageContract


class TestBillingStorageMemory(BillingStorageContract):
    @pytest.fixture
    def storage(self) -> BillingStorageInterface:
        return BillingStorageMemoryImpl(OutboxStorageMemoryImpl())
