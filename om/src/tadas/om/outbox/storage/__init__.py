"""Storage of the outbox. A row is never written on its own: the storage
base lands it in the same commit as the core row (`_insert(..., outbox_row)`
and `_upsert(..., outbox_row)` in the `core` role). The claim and the purge
are cross-tenant and serve the sweep."""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from uuid import UUID

from tadas.om.outbox.types.row import OutboxRow


class OutboxLandingInterface(ABC):
    """What a storage base needs from the outbox: somewhere for the row to land
    in the same commit as the core row. The Postgres base lands it in its own
    session; the memory base lands it here."""

    @abstractmethod
    def land(self, org_id: UUID, row: OutboxRow) -> None: ...


class OutboxStorageInterface(ABC):
    @abstractmethod
    async def claim_pending(
        self,
        limit: int,
        now: datetime,
        grace: timedelta,
        backoff_base: timedelta,
        backoff_cap: timedelta,
    ) -> list[tuple[UUID, OutboxRow]]:
        """Cross-tenant, for the sweep, one statement: up to `limit` rows that are
        neither done nor failed, whose next attempt is due at `now`, and that
        landed before `now - grace` (a younger row is the request path's to
        relay), oldest first, skipping rows another sweep holds locked. Each row
        returned has spent one more attempt and carries its next attempt, `now`
        plus a delay that doubles per attempt (`rules.relay_delay`), so a row
        that will not relay stops nothing behind it and two concurrent sweeps
        relay disjoint sets. Returns the rows as written, with their tenant."""
        ...

    @abstractmethod
    async def mark_done(self, org_id: UUID, row_id: UUID) -> None:
        """Stamps `done_at`; a row already done, or unknown, is left as is."""
        ...

    @abstractmethod
    async def record_failure(
        self, org_id: UUID, row_id: UUID, error: str, failed_at: datetime | None
    ) -> None:
        """Stamps `last_error` on a row that is not done, and `failed_at` when
        given: the row is then a dead letter, never claimed again, purged with
        the done ones. A row already done, or unknown, is left as is."""
        ...

    @abstractmethod
    async def purge_done(self, before: datetime) -> int:
        """Cross-tenant, for the sweep: deletes rows done or failed before
        `before`; returns how many."""
        ...
