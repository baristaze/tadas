import pytest
from contracts.billing_storage import BillingStorageContract

from tadas.om.billing.storage import BillingStorageInterface
from tadas.om.billing.storage.impl.postgres import BillingStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole

pytestmark = pytest.mark.integration


class TestBillingStoragePostgres(BillingStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> BillingStorageInterface:
        return BillingStoragePostgresImpl(pg_sessions)
