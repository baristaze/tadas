import pytest
from contracts.media_storage import MediaStorageContract

from tadas.om.media.storage import MediaStorageInterface
from tadas.om.media.storage.impl.memory import MediaStorageMemoryImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl


class TestMediaStorageMemory(MediaStorageContract):
    @pytest.fixture
    def storage(self) -> MediaStorageInterface:
        return MediaStorageMemoryImpl(OutboxStorageMemoryImpl())
