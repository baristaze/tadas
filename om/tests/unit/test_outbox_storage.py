import pytest
from contracts.outbox_storage import OutboxStorageContract

from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.impl.memory import TasksStorageMemoryImpl


class TestOutboxStorageMemory(OutboxStorageContract):
    @pytest.fixture
    def outbox(self) -> OutboxStorageInterface:
        return OutboxStorageMemoryImpl()

    @pytest.fixture
    def tasks(self, outbox: OutboxStorageMemoryImpl) -> TasksStorageInterface:
        return TasksStorageMemoryImpl(outbox)
