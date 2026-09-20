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
        included. Raises DuplicateWorkItem when another item carries the same
        idempotency key, TenantMismatch when the id is another tenant's row."""
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
        token, and the lease."""
        ...

    @abstractmethod
    async def requeue_stale(
        self, org_id: UUID, now: datetime, stagger: timedelta, updated_by: UUID
    ) -> list[WorkItem]:
        """One conditional statement: every claimed item of the tenant whose lease
        expired before `now` goes back to the queue, staggered by its position, or
        fails when its attempts are spent, its claim token cleared either way so
        the holder it had is refused; returns the items it changed, by id.
        `updated_by` is the sweep's principal."""
        ...

    @abstractmethod
    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None: ...
