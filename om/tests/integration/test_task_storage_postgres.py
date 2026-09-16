import pytest
from contracts.task_storage import TaskStorageContract

from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.impl.postgres import TasksStoragePostgresImpl

pytestmark = pytest.mark.integration


class TestTaskStoragePostgres(TaskStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> TasksStorageInterface:
        return TasksStoragePostgresImpl(pg_sessions)
