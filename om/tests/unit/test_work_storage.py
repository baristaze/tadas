import pytest

from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.storage.impl.memory import WorkStorageMemoryImpl

from contracts.work_storage import WorkStorageContract


class TestWorkStorageMemory(WorkStorageContract):
    @pytest.fixture
    def storage(self) -> WorkStorageInterface:
        return WorkStorageMemoryImpl()
