"""Storage of the work queue. The claim is the one named atomic method and
the one cross-tenant read; every other operation takes org_id first. The
writes that move a claimed item are conditional on the claim still being
this worker's, so a lost lease can never be written over."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from tadas.om.work.types.work_item import WorkItem, WorkKind


class WorkStorageInterface:
    async def write_item(self, org_id: UUID, item: WorkItem) -> None:
        """Raises DuplicateWorkItem when another item carries the same idempotency key."""
        ...

    async def write_item_if_held(
        self, org_id: UUID, worker_id: str, item: WorkItem
    ) -> WorkItem | None:
        """One conditional statement: writes `item` over its row only while the row
        is still claimed by `worker_id`; returns None when it is not."""
        ...

    async def claim_next(
        self, queue: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[UUID, WorkItem] | None:
        """Cross-tenant claim, one statement: the oldest available row in the queue,
        skipping locked ones, stamped with the claim and the lease."""
        ...

    async def requeue_stale(
        self, org_id: UUID, now: datetime, stagger: timedelta
    ) -> list[WorkItem]:
        """One conditional statement: every claimed item of the tenant whose lease
        expired before `now` goes back to the queue, staggered by its position, or
        fails when its attempts are spent; returns the items it changed, by id."""
        ...

    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None: ...
