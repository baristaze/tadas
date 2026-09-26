import pytest
from contracts.tenancy_storage import TenancyStorageContract

from tadas.om.billing.storage import BillingStorageInterface
from tadas.om.billing.storage.impl.memory import BillingStorageMemoryImpl
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.storage.impl.memory import IdempotencyStorageMemoryImpl
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl


class TestTenancyStorageMemory(TenancyStorageContract):
    @pytest.fixture
    def outbox(self) -> OutboxStorageInterface:
        return OutboxStorageMemoryImpl()

    @pytest.fixture
    def markers(self) -> IdempotencyStorageInterface:
        return IdempotencyStorageMemoryImpl()

    @pytest.fixture
    def accounts(self) -> BillingStorageInterface:
        return BillingStorageMemoryImpl()

    @pytest.fixture
    def storage(
        self,
        outbox: OutboxStorageInterface,
        markers: IdempotencyStorageInterface,
        accounts: BillingStorageInterface,
    ) -> TenancyStorageInterface:
        # The root wires the same three stores into the tenancy impl; the
        # memory twin of the outbox row landing in the commit, the marker
        # being read in the statement, and the account joined to a key's
        # principal.
        assert isinstance(outbox, OutboxStorageMemoryImpl)
        assert isinstance(markers, IdempotencyStorageMemoryImpl)
        return TenancyStorageMemoryImpl(outbox, markers, accounts)
