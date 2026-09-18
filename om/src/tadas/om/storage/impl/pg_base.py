"""The Postgres base every namespace storage shares: per-statement role
routing and the write primitives: an upsert that checks the tenant and lands
the core row's outbox row in the same commit, and an insert that refuses an
existing id."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import Table
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.util import find_tables

from tadas.om.base import Identifiable
from tadas.om.exceptions import Conflict, CrossRoleStatement, TenantMismatch
from tadas.om.outbox.storage.tables.outbox_rows import OutboxRows
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.roles import DatabaseRole, role_for
from tadas.om.storage.utils.translation import apply_row, to_row

SessionFactory = async_sessionmaker[AsyncSession]


def role_of(target: Any) -> DatabaseRole:
    """The one role a statement or a table class touches; refuses a statement that spans two."""
    if isinstance(target, type):
        return role_for(target.__tablename__)
    tables = find_tables(
        target,
        check_columns=True,
        include_aliases=True,
        include_joins=True,
        include_selects=True,
        include_crud=True,
    )
    roles = {role_for(table.name) for table in tables if isinstance(table, Table)}
    if len(roles) != 1:
        raise CrossRoleStatement(f"statement touches roles {sorted(r.value for r in roles)}")
    return roles.pop()


class PgStorageBase:
    def __init__(self, sessions: Mapping[DatabaseRole, SessionFactory]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def _session_for(self, target: Any) -> AsyncIterator[AsyncSession]:
        """A short session on the pool of the one role `target` touches."""
        factory = self._sessions[role_of(target)]
        async with factory() as session:
            yield session

    async def _upsert(
        self,
        row_type: type[Any],
        org_id: UUID,
        entity: Identifiable,
        outbox_row: OutboxRow | None = None,
    ) -> None:
        """Insert or update by id, refusing to overwrite another tenant's row, then
        commit. An `outbox_row` is inserted in the same commit: the core row and
        its handoff land together or not at all (the transactional outbox), which
        is why every table with an outbox row lives in the `core` role."""
        entity_id = entity.id
        async with self._session_for(row_type) as session:
            row = await session.get(row_type, entity_id)
            if row is None:
                session.add(to_row(entity, row_type, org_id=org_id))
            else:
                if row.org_id != org_id:
                    raise TenantMismatch(f"{row_type.__tablename__} {entity_id} is not in {org_id}")
                apply_row(row, entity)
            if outbox_row is not None:
                role_of(OutboxRows)  # the same role as row_type, or the session cannot hold both
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()

    async def _insert(self, row_type: type[Any], org_id: UUID, entity: Identifiable) -> None:
        """Insert by id, raising Conflict when the id exists, then commit. For an
        append-only row that is never upserted."""
        async with self._session_for(row_type) as session:
            session.add(to_row(entity, row_type, org_id=org_id))
            try:
                await session.commit()
            except IntegrityError as error:
                raise Conflict(f"{row_type.__tablename__} {entity.id} already exists") from error

    async def _upsert_global(self, row_type: type[Any], entity: Identifiable) -> None:
        """The same primitive for a global table, which has no tenant to check."""
        entity_id = entity.id
        async with self._session_for(row_type) as session:
            row = await session.get(row_type, entity_id)
            if row is None:
                session.add(to_row(entity, row_type))
            else:
                apply_row(row, entity)
            await session.commit()
