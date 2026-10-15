import pytest

from tadas.om.orchestrations.storage import OrchestrationsStorageInterface
from tadas.om.orchestrations.storage.impl.memory import OrchestrationsStorageMemoryImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl

from contracts.orchestration_storage import OrchestrationStorageContract


class TestOrchestrationStorageMemory(OrchestrationStorageContract):
    @pytest.fixture
    def storage(self) -> OrchestrationsStorageInterface:
        return OrchestrationsStorageMemoryImpl(OutboxStorageMemoryImpl())
