"""The transactional outbox: a handoff that follows a core write (the event
row behind every push) is never a second statement a manager remembers to
make. The manager writes the core row and an `OutboxRow` in one named
atomic storage method, then relays the row at once; the maintenance sweep
relays whatever a crash left behind and purges what is done. The relay is
idempotent on the row's id, so relaying twice is harmless."""

from abc import ABC, abstractmethod
from datetime import timedelta
from uuid import UUID

from tadas.om.outbox.types.row import OutboxRow


class OutboxRelayInterface(ABC):
    @abstractmethod
    async def relay(self, org_id: UUID, row: OutboxRow) -> bool:
        """Appends the `Event` the row describes (idempotent on the row's id),
        publishes ENTITY_CHANGED with (kind, target_id, seq), and marks the row
        done. Returns False, and never raises, when a step failed: the row is
        durable and the sweep relays it again."""
        ...

    @abstractmethod
    async def relay_pending(self, limit: int) -> int:
        """Platform-internal, for the sweep: relays up to `limit` rows a crash left
        behind, oldest first; returns how many were relayed."""
        ...

    @abstractmethod
    async def purge_done(self, retention: timedelta) -> int:
        """Platform-internal, for the sweep: deletes rows done longer ago than
        `retention`; returns how many. The one hard delete of the namespace."""
        ...
