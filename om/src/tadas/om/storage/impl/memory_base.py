"""The in-memory base: a full second implementation of every tenancy rule
the relational base has, over dicts keyed by id. An outbox row lands in the
outbox memory storage the root handed this impl, the twin of "in the same
commit"."""

import asyncio
from typing import TYPE_CHECKING, Protocol, TypeVar
from uuid import UUID

from tadas.om.exceptions import Conflict, TenantMismatch
from tadas.om.outbox.types.row import OutboxRow

if TYPE_CHECKING:
    # The memory outbox impl is the landing place, not an interface: a concrete
    # twin of the Postgres session that holds both rows.
    from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl


class HasId(Protocol):
    @property
    def id(self) -> UUID: ...


E = TypeVar("E", bound=HasId)

MemoryTable = dict[UUID, tuple[UUID, E]]
"""id -> (org_id, entity). Both impls sort by the UUID value, never by its string."""


class MemoryStorageBase:
    def __init__(self, outbox: OutboxStorageMemoryImpl | None = None) -> None:
        self._lock = asyncio.Lock()
        self._outbox = outbox

    @property
    def outbox(self) -> OutboxStorageMemoryImpl:
        """The outbox this impl lands rows in; a core-role impl is built with one."""
        if self._outbox is None:
            raise RuntimeError("this memory storage was built without an outbox to land in")
        return self._outbox

    def _put(
        self, table: MemoryTable[E], org_id: UUID, entity: E, outbox_row: OutboxRow | None = None
    ) -> None:
        existing = table.get(entity.id)
        if existing is not None and existing[0] != org_id:
            raise TenantMismatch(f"{entity.id} is not in {org_id}")
        if outbox_row is not None:
            if self._outbox is None:
                raise RuntimeError("this memory storage was built without an outbox to land in")
            self._outbox.land(org_id, outbox_row)
        table[entity.id] = (org_id, entity)

    @staticmethod
    def _insert(table: MemoryTable[E], org_id: UUID, entity: E) -> None:
        if entity.id in table:
            raise Conflict(f"{entity.id} already exists")
        table[entity.id] = (org_id, entity)

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
