from datetime import datetime
from uuid import UUID

from tadas.om.billing.storage import BillingStorageInterface
from tadas.om.billing.types.account import BillingAccount
from tadas.om.billing.types.delivery import BillingDelivery
from tadas.om.exceptions import UniqueKeyTaken
from tadas.om.outbox.storage import OutboxLandingInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class BillingStorageMemoryImpl(MemoryStorageBase, BillingStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._accounts: MemoryTable[BillingAccount] = {}
        self._deliveries: MemoryTable[BillingDelivery] = {}

    async def read_account(self, org_id: UUID) -> BillingAccount | None:
        found = self._rows(self._accounts, org_id)
        return found[0] if found else None

    async def create_account(
        self, org_id: UUID, account: BillingAccount, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            # The org is the unique key, as the index is in Postgres.
            if self._rows(self._accounts, org_id):
                return False
            return self._insert(self._accounts, org_id, account, outbox_rows)

    async def write_account(
        self,
        org_id: UUID,
        account: BillingAccount,
        outbox_rows: tuple[OutboxRow, ...],
        delivery: BillingDelivery | None = None,
    ) -> bool:
        # The mark, the account, and the rows land in one step under the
        # lock, as they share one transaction in Postgres; a mark already
        # there, under any tenant, lands nothing.
        async with self._lock:
            if delivery is not None and delivery.id in self._deliveries:
                return False
            self._fence(self._accounts, org_id, account)
            held = self._rows(self._accounts, org_id)
            if held and held[0].id != account.id:
                raise UniqueKeyTaken(f"billing_accounts {account.id}: the org has another account")
            self._put(self._accounts, org_id, account, outbox_rows)
            if delivery is not None:
                self._deliveries[delivery.id] = (org_id, delivery)
            return True

    async def read_delivery(self, org_id: UUID, delivery_id: UUID) -> BillingDelivery | None:
        return self._get(self._deliveries, org_id, delivery_id)

    async def purge_deliveries(self, org_id: UUID, before: datetime) -> int:
        async with self._lock:
            gone = [d.id for d in self._rows(self._deliveries, org_id) if d.created_at < before]
            for delivery_id in gone:
                del self._deliveries[delivery_id]
            return len(gone)

    async def purge_tenant(self, org_id: UUID) -> int:
        async with self._lock:
            accounts = [a.id for a in self._rows(self._accounts, org_id)]
            deliveries = [d.id for d in self._rows(self._deliveries, org_id)]
            for account_id in accounts:
                del self._accounts[account_id]
            for delivery_id in deliveries:
                del self._deliveries[delivery_id]
            return len(accounts) + len(deliveries)
