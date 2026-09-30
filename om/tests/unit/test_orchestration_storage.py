import pytest
from contracts.orchestration_storage import OrchestrationStorageContract

from tadas.om.orchestrations.storage import OrchestrationsStorageInterface
from tadas.om.orchestrations.storage.impl.memory import OrchestrationsStorageMemoryImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl


class TestOrchestrationStorageMemory(OrchestrationStorageContract):
    @pytest.fixture
    def storage(self) -> OrchestrationsStorageInterface:
        return OrchestrationsStorageMemoryImpl(OutboxStorageMemoryImpl())
