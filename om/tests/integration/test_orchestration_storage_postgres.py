import pytest
from contracts.orchestration_storage import OrchestrationStorageContract

from tadas.om.orchestrations.storage import OrchestrationsStorageInterface
from tadas.om.orchestrations.storage.impl.postgres import OrchestrationsStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole

pytestmark = pytest.mark.integration


class TestOrchestrationStoragePostgres(OrchestrationStorageContract):
    @pytest.fixture
    def storage(
        self, pg_sessions: dict[DatabaseRole, SessionFactory]
    ) -> OrchestrationsStorageInterface:
        return OrchestrationsStoragePostgresImpl(pg_sessions)
