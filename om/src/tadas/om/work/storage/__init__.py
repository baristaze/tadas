"""Storage of the work queue. The claim is the one named atomic method and
the one cross-tenant read; every other operation takes org_id first. The
claim mints a token, and the writes that move a claimed item are conditional
on that token still being on the row, so a lost lease can never be written
over, not even by the worker that held the item before and holds it again."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from tadas.om.work.types.work_item import WorkItem, WorkKind


class WorkStorageInterface(ABC):
    @abstractmethod
    async def create_item(self, org_id: UUID, item: WorkItem) -> bool:
        """The create primitive: inserts the row and commits; False when the id is
        already written, in which case nothing changes, the claim on the row
        included. A taken idempotency key is reported the same way and never
        raised as a driver error, which is what makes the relayed enqueue safe
        to run twice: the relay presents the outbox row's id as the key on
        every run and meets the row already there. Raises TenantMismatch when
        the id is another tenant's row."""
        ...

    @abstractmethod
    async def read_item_by_key(self, org_id: UUID, idempotency_key: UUID) -> WorkItem | None:
        """The row the tenant already holds under this key, for the create that
        reported one; None when the key is unknown here. The key is unique
        across tenants, so a key another tenant holds reads back as None."""
        ...

    @abstractmethod
    async def write_item_if_held(
        self, org_id: UUID, claim_token: UUID, item: WorkItem
    ) -> WorkItem | None:
        """One conditional statement: writes `item` over its row only while the row
        is still claimed under `claim_token`; returns None when it is not."""
        ...

    @abstractmethod
    async def claim_next(
        self, lane: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[UUID, WorkItem] | None:
        """Cross-tenant claim, one statement: the oldest available row on the lane,
        skipping locked ones, stamped with the claim, a freshly minted claim
        token, and the lease. The claim is the platform's write, so it signs
        `updated_by` with EMPTY_UUID."""
        ...

    @abstractmethod
    async def requeue_stale(
        self, org_id: UUID, now: datetime, stagger: timedelta, limit: int
    ) -> list[WorkItem]:
        """One conditional statement: the claimed items of the tenant whose lease
        expired before `now`, the first `limit` of them by id, go back to the
        queue, staggered by their position, or fail when their attempts are
        spent, the claim token cleared either way so the holder it had is
        refused; returns the items it changed, by id. The caller picks the
        bound: the sweep passes its batch size and takes the rest next tick.
        The requeue is the platform's write, like the claim, so it signs
        `updated_by` with EMPTY_UUID and takes no principal."""
        ...

    @abstractmethod
    async def purge_settled(self, org_id: UUID, before: datetime) -> int:
        """For the sweep, per tenant: deletes items done or failed whose last
        change was before `before`; returns how many. The one hard delete of the
        namespace."""
        ...

    @abstractmethod
    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None: ...
