import pytest
from contracts.task_storage import TaskStorageContract

from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.impl.memory import TasksStorageMemoryImpl


class TestTaskStorageMemory(TaskStorageContract):
    @pytest.fixture
    def storage(self) -> TasksStorageInterface:
        return TasksStorageMemoryImpl()
