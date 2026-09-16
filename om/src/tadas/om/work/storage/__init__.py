"""Storage of the work queue. The claim is the one named atomic method;
the sweep crosses tenants on purpose and returns the tenant with each row."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from tadas.om.work.types.work_item import WorkItem, WorkKind


class WorkStorageInterface:
    async def write_item(self, org_id: UUID, item: WorkItem) -> None:
        """Raises DuplicateWorkItem when another item carries the same idempotency key."""
        ...

    async def claim_next(
        self, queue: str, kinds: Sequence[WorkKind], worker_id: str, lease: timedelta
    ) -> tuple[UUID, WorkItem] | None:
        """Cross-tenant claim, one statement: the oldest available row in the queue,
        skipping locked ones, stamped with the claim and the lease."""
        ...

    async def read_stale(self, before: datetime) -> list[tuple[UUID, WorkItem]]:
        """Cross-tenant sweep: claimed items whose lease expired before `before`."""
        ...

    async def read_item(self, org_id: UUID, item_id: UUID) -> WorkItem | None: ...
