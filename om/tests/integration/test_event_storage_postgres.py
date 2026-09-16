import pytest
from contracts.event_storage import EventStorageContract

from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.storage.impl.postgres import EventStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole

pytestmark = pytest.mark.integration


class TestEventStoragePostgres(EventStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> EventStorageInterface:
        return EventStoragePostgresImpl(pg_sessions)
