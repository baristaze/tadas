import pytest
from contracts.media_storage import MediaStorageContract

from tadas.om.media.storage import MediaStorageInterface
from tadas.om.media.storage.impl.postgres import MediaStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole

pytestmark = pytest.mark.integration


class TestMediaStoragePostgres(MediaStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> MediaStorageInterface:
        return MediaStoragePostgresImpl(pg_sessions)
