import pytest
from contracts.slack_storage import SlackStorageContract

from tadas.om.slack.storage import SlackStorageInterface
from tadas.om.slack.storage.impl.postgres import SlackStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole

pytestmark = pytest.mark.integration


class TestSlackStoragePostgres(SlackStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> SlackStorageInterface:
        return SlackStoragePostgresImpl(pg_sessions)
