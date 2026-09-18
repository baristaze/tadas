import pytest
from contracts.outbox_storage import OutboxStorageContract

from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.storage.impl.postgres import OutboxStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.impl.postgres import TasksStoragePostgresImpl

pytestmark = pytest.mark.integration


class TestOutboxStoragePostgres(OutboxStorageContract):
    @pytest.fixture
    def outbox(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> OutboxStorageInterface:
        return OutboxStoragePostgresImpl(pg_sessions)

    @pytest.fixture
    def tasks(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> TasksStorageInterface:
        return TasksStoragePostgresImpl(pg_sessions)
