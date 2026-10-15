import pytest

from tadas.om.media.storage import MediaStorageInterface
from tadas.om.media.storage.impl.memory import MediaStorageMemoryImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl

from contracts.media_storage import MediaStorageContract


class TestMediaStorageMemory(MediaStorageContract):
    @pytest.fixture
    def storage(self) -> MediaStorageInterface:
        return MediaStorageMemoryImpl(OutboxStorageMemoryImpl())
