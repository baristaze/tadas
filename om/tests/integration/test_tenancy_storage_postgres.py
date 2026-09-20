import pytest
from contracts.tenancy_storage import TenancyStorageContract

from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.storage.impl.postgres import IdempotencyStoragePostgresImpl
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.storage.impl.postgres import OutboxStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.postgres import TenancyStoragePostgresImpl

pytestmark = pytest.mark.integration


class TestTenancyStoragePostgres(TenancyStorageContract):
    @pytest.fixture
    def outbox(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> OutboxStorageInterface:
        return OutboxStoragePostgresImpl(pg_sessions)

    @pytest.fixture
    def markers(
        self, pg_sessions: dict[DatabaseRole, SessionFactory]
    ) -> IdempotencyStorageInterface:
        return IdempotencyStoragePostgresImpl(pg_sessions)

    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> TenancyStorageInterface:
        return TenancyStoragePostgresImpl(pg_sessions)
