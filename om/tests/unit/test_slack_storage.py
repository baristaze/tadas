import pytest

from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.slack.storage import SlackStorageInterface
from tadas.om.slack.storage.impl.memory import SlackStorageMemoryImpl

from contracts.slack_storage import SlackStorageContract


class TestSlackStorageMemory(SlackStorageContract):
    @pytest.fixture
    def storage(self) -> SlackStorageInterface:
        return SlackStorageMemoryImpl(OutboxStorageMemoryImpl())
