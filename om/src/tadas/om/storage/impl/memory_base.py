"""The in-memory base: a full second implementation of every tenancy rule
the relational base has, over dicts keyed by id."""

import asyncio
from typing import Protocol, TypeVar
from uuid import UUID

from tadas.om.exceptions import TenantMismatch


class HasId(Protocol):
    @property
    def id(self) -> UUID: ...


E = TypeVar("E", bound=HasId)

MemoryTable = dict[UUID, tuple[UUID, E]]
"""id -> (org_id, entity). Both impls sort by the UUID value, never by its string."""


class MemoryStorageBase:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @staticmethod
    def _put(table: MemoryTable[E], org_id: UUID, entity: E) -> None:
        existing = table.get(entity.id)
        if existing is not None and existing[0] != org_id:
            raise TenantMismatch(f"{entity.id} is not in {org_id}")
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
