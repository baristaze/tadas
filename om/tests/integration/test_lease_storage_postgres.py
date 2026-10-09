import pytest
from contracts.lease_storage import LeaseStorageContract

from tadas.om.leases.storage import LeasesStorageInterface
from tadas.om.leases.storage.impl.postgres import LeasesStoragePostgresImpl
from tadas.om.orchestrations.storage import OrchestrationsStorageInterface
from tadas.om.orchestrations.storage.impl.postgres import OrchestrationsStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole

pytestmark = pytest.mark.integration


class TestLeaseStoragePostgres(LeaseStorageContract):
    @pytest.fixture
    def records(
        self, pg_sessions: dict[DatabaseRole, SessionFactory]
    ) -> OrchestrationsStorageInterface:
        return OrchestrationsStoragePostgresImpl(pg_sessions)

    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> LeasesStorageInterface:
        return LeasesStoragePostgresImpl(pg_sessions)
