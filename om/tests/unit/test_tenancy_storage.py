import pytest
from contracts.tenancy_storage import TenancyStorageContract

from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl


class TestTenancyStorageMemory(TenancyStorageContract):
    @pytest.fixture
    def storage(self) -> TenancyStorageInterface:
        return TenancyStorageMemoryImpl()
