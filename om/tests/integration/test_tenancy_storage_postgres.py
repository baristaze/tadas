import pytest

from tadas.om.billing.storage import BillingStorageInterface
from tadas.om.billing.storage.impl.postgres import BillingStoragePostgresImpl
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.storage.impl.postgres import IdempotencyStoragePostgresImpl
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.storage.impl.postgres import OutboxStoragePostgresImpl
from tadas.om.storage.impl.pg_base import SessionFactory
from tadas.om.storage.roles import DatabaseRole
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.postgres import TenancyStoragePostgresImpl

from contracts.tenancy_credentials_storage import TenancyCredentialsStorageContract
from contracts.tenancy_members_storage import TenancyMembersStorageContract
from contracts.tenancy_org_storage import TenancyOrgStorageContract
from contracts.tenancy_sign_in_storage import TenancySignInStorageContract
from contracts.tenancy_storage import TenancyStorageContract

pytestmark = pytest.mark.integration


class TestTenancyStoragePostgres(
    TenancyCredentialsStorageContract,
    TenancyMembersStorageContract,
    TenancyOrgStorageContract,
    TenancySignInStorageContract,
    TenancyStorageContract,
):
    @pytest.fixture
    def outbox(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> OutboxStorageInterface:
        return OutboxStoragePostgresImpl(pg_sessions)

    @pytest.fixture
    def markers(
        self, pg_sessions: dict[DatabaseRole, SessionFactory]
    ) -> IdempotencyStorageInterface:
        return IdempotencyStoragePostgresImpl(pg_sessions)

    @pytest.fixture
    def accounts(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> BillingStorageInterface:
        return BillingStoragePostgresImpl(pg_sessions)

    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> TenancyStorageInterface:
        return TenancyStoragePostgresImpl(pg_sessions)
