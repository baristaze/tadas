"""Storage of the outbox. A row is never written on its own: the storage
base lands it in the same commit as the core row (`_upsert(..., outbox_row)`
in the `core` role). The two cross-tenant reads here serve the sweep."""

from datetime import datetime
from uuid import UUID

from tadas.om.outbox.types.row import OutboxRow


class OutboxLandingInterface:
    """What a storage base needs from the outbox: somewhere for the row to land
    in the same commit as the core row. The Postgres base lands it in its own
    session; the memory base lands it here."""

    def land(self, org_id: UUID, row: OutboxRow) -> None: ...


class OutboxStorageInterface:
    async def read_pending(self, limit: int) -> list[tuple[UUID, OutboxRow]]:
        """Cross-tenant, for the sweep: rows not yet done, oldest first, with their tenant."""
        ...

    async def mark_done(self, org_id: UUID, row_id: UUID) -> None:
        """Stamps `done_at`; a row already done, or unknown, is left as is."""
        ...

    async def purge_done(self, before: datetime) -> int:
        """Cross-tenant, for the sweep: deletes rows done before `before`; returns how many."""
        ...
