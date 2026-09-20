"""The in-memory base: a full second implementation of every tenancy rule
the relational base has, over dicts keyed by id. An outbox row lands in the
outbox memory storage the root handed this impl, the twin of "in the same
commit"."""

import asyncio
from collections.abc import Iterator
from typing import Protocol, TypeVar
from uuid import UUID

from tadas.om.exceptions import RowDeleted, TenantMismatch
from tadas.om.outbox.storage import OutboxLandingInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.utils.translation import undeletes


class HasId(Protocol):
    @property
    def id(self) -> UUID: ...


E = TypeVar("E", bound=HasId)

MemoryTable = dict[UUID, tuple[UUID, E]]
"""id -> (org_id, entity). Both impls sort by the UUID value, never by its string."""


class MemoryStorageBase:
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        self._lock = asyncio.Lock()
        self._outbox = outbox

    def _put(
        self, table: MemoryTable[E], org_id: UUID, entity: E, outbox_row: OutboxRow | None = None
    ) -> None:
        existing = table.get(entity.id)
        if existing is not None and existing[0] != org_id:
            raise TenantMismatch(f"{entity.id} is not in {org_id}")
        if existing is not None and undeletes(existing[1], entity):
            raise RowDeleted(f"{entity.id} was deleted")
        if outbox_row is not None:
            if self._outbox is None:
                raise RuntimeError("this memory storage was built without an outbox to land in")
            self._outbox.land(org_id, outbox_row)
        table[entity.id] = (org_id, entity)

    def _insert(
        self, table: MemoryTable[E], org_id: UUID, entity: E, outbox_row: OutboxRow | None = None
    ) -> bool:
        """The create primitive: False when the id is already written, and nothing
        changes then, the outbox row included."""
        if entity.id in table:
            return False
        if outbox_row is not None:
            if self._outbox is None:
                raise RuntimeError("this memory storage was built without an outbox to land in")
            self._outbox.land(org_id, outbox_row)
        table[entity.id] = (org_id, entity)
        return True

    @staticmethod
    def _get(table: MemoryTable[E], org_id: UUID, entity_id: UUID) -> E | None:
        found = table.get(entity_id)
        if found is None or found[0] != org_id:
            return None
        return found[1]

    @staticmethod
    def _rows(table: MemoryTable[E], org_id: UUID) -> list[E]:
        return sorted(
            (entity for row_org, entity in table.values() if row_org == org_id),
            key=lambda entity: entity.id,
        )

    @staticmethod
    def _rows_across_tenants(table: MemoryTable[E]) -> list[tuple[UUID, E]]:
        return sorted(table.values(), key=lambda pair: pair[1].id)

    @staticmethod
    def _every(table: MemoryTable[E]) -> Iterator[E]:
        """Every entity of a table, any tenant, unordered: for a key that is
        unique across tenants (a token hash, a slug)."""
        return (entity for _, entity in table.values())
