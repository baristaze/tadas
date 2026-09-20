"""The Postgres base every namespace storage shares: per-statement role
routing and the write primitives: an upsert that checks the tenant and lands
the core row's outbox rows in the same commit, and an insert that refuses an
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
from tadas.om.exceptions import (
    CrossRoleStatement,
    RowDeleted,
    TenantMismatch,
    UniqueKeyTaken,
)
from tadas.om.outbox.storage.tables.outbox_rows import OutboxRows
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.roles import DatabaseRole, role_for
from tadas.om.storage.utils.translation import apply_row, to_row, undeletes

SessionFactory = async_sessionmaker[AsyncSession]


def violated_constraint(error: IntegrityError) -> str | None:
    """The name of the constraint an integrity error names, or None when the
    driver does not say. The asyncpg adapter wraps the driver's error, which
    carries `constraint_name`, as the cause of the one SQLAlchemy raises."""
    cause: BaseException | None = error.orig
    while cause is not None:
        name = getattr(cause, "constraint_name", None)
        if isinstance(name, str):
            return name
        cause = cause.__cause__
    return None


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
        outbox_rows: tuple[OutboxRow, ...] = (),
    ) -> None:
        """Insert or update by id, refusing to overwrite another tenant's row, then
        commit. The `outbox_rows` are inserted in the same commit: the core row
        and its handoffs land together or not at all (the transactional outbox),
        which is why every table with an outbox row lives in the `core` role. An
        entity change is one row; a write that also starts work carries a second
        row of kind `work.<kind>` in the same tuple, because the queue is a role
        of its own and no statement reaches both.

        A write never brings a soft-deleted row back. Every update here is a
        read, a copy, and a write of the whole entity, so a delete that commits
        between the read and the write would otherwise be undone by an
        `updated_at` copy that still carries `deleted_at = NULL`. There is no
        restore in this domain; `RowDeleted` says the row went while the
        caller was holding it, and the caller reads it again."""
        entity_id = entity.id
        if outbox_rows and role_of(row_type) is not role_of(OutboxRows):
            raise CrossRoleStatement(
                f"{row_type.__tablename__} is not in the outbox's role; no outbox row"
            )
        async with self._session_for(row_type) as session:
            row = await session.get(row_type, entity_id)
            if row is None:
                session.add(to_row(entity, row_type, org_id=org_id))
            else:
                if row.org_id != org_id:
                    raise TenantMismatch(f"{row_type.__tablename__} {entity_id} is not in {org_id}")
                if undeletes(row, entity):
                    raise RowDeleted(f"{row_type.__tablename__} {entity_id} was deleted")
                apply_row(row, entity)
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            try:
                await session.commit()
            except IntegrityError as error:
                # A key race the read did not see; a Conflict, never a driver error.
                raise UniqueKeyTaken(
                    f"{row_type.__tablename__} {entity.id}: "
                    f"{violated_constraint(error) or 'a unique key'} is taken"
                ) from error

    async def _insert(
        self,
        row_type: type[Any],
        org_id: UUID,
        entity: Identifiable,
        outbox_rows: tuple[OutboxRow, ...] = (),
    ) -> bool:
        """The create primitive: insert by id and commit, with the outbox rows in
        the same commit; False when the id is already written, in which case
        nothing changes, the outbox rows included. Ids are minted above storage,
        so an existing id is a retry, and a retry must neither overwrite the row
        nor announce it twice. Only the primary key reports False: any other
        unique key the row violates is `UniqueKeyTaken`, a Conflict, never a
        driver error and never mistaken for a retry."""
        if outbox_rows and role_of(row_type) is not role_of(OutboxRows):
            raise CrossRoleStatement(
                f"{row_type.__tablename__} is not in the outbox's role; no outbox row"
            )
        async with self._session_for(row_type) as session:
            session.add(to_row(entity, row_type, org_id=org_id))
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                constraint = violated_constraint(error)
                if constraint == row_type.__table__.primary_key.name:
                    return False
                raise UniqueKeyTaken(
                    f"{row_type.__tablename__} {entity.id}: {constraint or 'a unique key'} is taken"
                ) from error
            return True

    async def _upsert_global(self, row_type: type[Any], entity: Identifiable) -> None:
        """The same primitive for a global table, which has no tenant to check;
        a unique key the read did not see is `UniqueKeyTaken` here too."""
        entity_id = entity.id
        async with self._session_for(row_type) as session:
            row = await session.get(row_type, entity_id)
            if row is None:
                session.add(to_row(entity, row_type))
            else:
                apply_row(row, entity)
            try:
                await session.commit()
            except IntegrityError as error:
                raise UniqueKeyTaken(
                    f"{row_type.__tablename__} {entity_id}: "
                    f"{violated_constraint(error) or 'a unique key'} is taken"
                ) from error
