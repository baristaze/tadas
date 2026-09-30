import pytest
from contracts.event_storage import EventStorageContract

from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl


class TestEventStorageMemory(EventStorageContract):
    @pytest.fixture
    def storage(self) -> EventStorageInterface:
        return EventStorageMemoryImpl()
