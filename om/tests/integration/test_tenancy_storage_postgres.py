import pytest
from contracts.tenancy_storage import TenancyStorageContract

from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.postgres import TenancyStoragePostgresImpl

pytestmark = pytest.mark.integration


class TestTenancyStoragePostgres(TenancyStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> TenancyStorageInterface:
        return TenancyStoragePostgresImpl(pg_sessions)
