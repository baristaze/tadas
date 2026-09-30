import pytest
from contracts.idempotency_storage import IdempotencyStorageContract

from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.storage.impl.postgres import IdempotencyStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole

pytestmark = pytest.mark.integration


class TestIdempotencyStoragePostgres(IdempotencyStorageContract):
    @pytest.fixture
    def storage(
        self, pg_sessions: dict[DatabaseRole, SessionFactory]
    ) -> IdempotencyStorageInterface:
        return IdempotencyStoragePostgresImpl(pg_sessions)
