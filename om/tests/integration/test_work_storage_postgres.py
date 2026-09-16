import pytest
from contracts.work_storage import WorkStorageContract

from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.storage.impl.postgres import WorkStoragePostgresImpl

pytestmark = pytest.mark.integration


class TestWorkStoragePostgres(WorkStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> WorkStorageInterface:
        return WorkStoragePostgresImpl(pg_sessions)
