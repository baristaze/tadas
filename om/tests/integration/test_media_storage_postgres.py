import pytest

from tadas.om.media.storage import MediaStorageInterface
from tadas.om.media.storage.impl.postgres import MediaStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole

from contracts.media_storage import MediaStorageContract

pytestmark = pytest.mark.integration


class TestMediaStoragePostgres(MediaStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> MediaStorageInterface:
        return MediaStoragePostgresImpl(pg_sessions)
