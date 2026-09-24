"""The Postgres base every namespace storage shares: per-statement role
routing, the funnel that names the scope of every transaction, and the write
primitives: an upsert that checks the tenant and lands the core row's outbox
rows in the same commit, and an insert that refuses an existing id."""

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import Table, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.util import find_tables

from tadas.om.base import EMPTY_UUID, Identifiable
from tadas.om.exceptions import (
    CrossRoleStatement,
    RowDeleted,
    TenantMismatch,
    UniqueKeyTaken,
)
from tadas.om.outbox.storage.tables.outbox_rows import OutboxRows
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.roles import DatabaseRole, role_for
from tadas.om.storage.scopes import IDENTITY_SETTING, ORG_SETTING, USER_SETTING
from tadas.om.storage.utils.translation import apply_row, to_row, undeletes

SessionFactory = async_sessionmaker[AsyncSession]


class LoginSessions(Mapping[DatabaseRole, SessionFactory]):
    """The session factories of every role under the two logins a process
    holds: the runtime login's, which is what the mapping itself answers, and
    the system login's beside them, which only the system scope opens. The
    system login's URL names another login, so its pool is its own."""

    def __init__(
        self,
        runtime: Mapping[DatabaseRole, SessionFactory],
        system: Mapping[DatabaseRole, SessionFactory],
    ) -> None:
        self._runtime = dict(runtime)
        self.system: Mapping[DatabaseRole, SessionFactory] = dict(system)

    def __getitem__(self, role: DatabaseRole) -> SessionFactory:
        return self._runtime[role]

    def __iter__(self) -> Iterator[DatabaseRole]:
        return iter(self._runtime)

    def __len__(self) -> int:
        return len(self._runtime)


SCOPE_SETTINGS: tuple[tuple[str, str], ...] = (
    (ORG_SETTING, "org_id"),
    (USER_SETTING, "user_id"),
    (IDENTITY_SETTING, "identity_id"),
)
"""Each transaction setting and the bind parameter that carries it. The
setting names are constants of this module; nothing a caller spells reaches
them, which is why they can be written into the statement."""


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


async def set_scope(
    session: AsyncSession,
    org_id: UUID,
    user_id: UUID | None,
    identity_id: UUID | None,
) -> None:
    """The scope of one transaction, as Postgres transaction settings. They are
    set with `set_config(name, value, true)`, so they die with the transaction
    and never leak onto the next caller of a pooled connection; `SET LOCAL`
    takes no bind parameter, which is why this is a `SELECT`. A setting that is
    not given is not set at all, and a policy reads it as NULL."""
    values = {"org_id": str(org_id)}
    if user_id is not None:
        values["user_id"] = str(user_id)
    if identity_id is not None:
        values["identity_id"] = str(identity_id)
    calls = ", ".join(
        f"set_config('{setting}', :{param}, true)"
        for setting, param in SCOPE_SETTINGS
        if param in values
    )
    await session.execute(text(f"SELECT {calls}"), values)


class PgStorageBase:
    def __init__(self, sessions: Mapping[DatabaseRole, SessionFactory]) -> None:
        """`sessions` is a `LoginSessions`: a plain mapping names one login,
        and the system scope has a login of its own, so it is refused rather
        than read as both."""
        if not isinstance(sessions, LoginSessions):
            raise TypeError("PgStorageBase takes LoginSessions: the runtime and the system login")
        self._sessions: LoginSessions = sessions

    @asynccontextmanager
    async def _session_for(
        self,
        target: Any,
        *,
        org_id: UUID,
        user_id: UUID | None = None,
        identity_id: UUID | None = None,
    ) -> AsyncIterator[AsyncSession]:
        """A short session on the pool of the one role `target` touches, opened
        under the scope of the call. Every connection of that pool carries the
        role's statement deadline from the moment it opens, so no statement
        here asks for one.

        This is the funnel: every statement of every impl passes here, so the
        tenant is named once per transaction and not once per query. `org_id`
        is required; `EMPTY_UUID` is the system scope, the transaction that
        reads across tenants, and it is never a default. `user_id` narrows a
        `both`-scoped table that names the user to one person, and
        `identity_id` narrows one whose person is the identity behind it
        (`users`) and is the person of an `identity`-scoped table.

        The system scope runs on the system login's pool and every other
        scope on the runtime login's. The policies admit the system scope to
        the system login alone, so a runtime connection that names
        `EMPTY_UUID` reads nothing.

        The settings go in before anything else, so they are the first
        statement of the transaction the session opens. A commit or a rollback
        ends that transaction and takes them with it, which is why a method
        that runs a second transaction opens a second session."""
        role = role_of(target)
        logins = self._sessions.system if org_id == EMPTY_UUID else self._sessions
        factory = logins[role]
        async with factory() as session:
            await set_scope(session, org_id, user_id, identity_id)
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
        caller was holding it, and the caller reads it again.

        Another tenant's row is refused twice. The read names the tenant on
        the row and says so, which is the fence this layer relies on. Under
        the policy that read never returns the row at all, so the insert that
        follows meets the primary key instead, and a primary key the read did
        not see is a row this transaction may not see: the same refusal, from
        the key rather than from the column. In a race inside one tenant, two
        writers of one new id meet the same key; the loser is told the row is
        not its tenant's when it is, and answers a Conflict the way it answers
        the other one, by reading the row again."""
        entity_id = entity.id
        if outbox_rows and role_of(row_type) is not role_of(OutboxRows):
            raise CrossRoleStatement(
                f"{row_type.__tablename__} is not in the outbox's role; no outbox row"
            )
        async with self._session_for(row_type, org_id=org_id) as session:
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
                constraint = violated_constraint(error)
                if row is None and constraint == row_type.__table__.primary_key.name:
                    raise TenantMismatch(
                        f"{row_type.__tablename__} {entity_id} is not in {org_id}"
                    ) from error
                raise UniqueKeyTaken(
                    f"{row_type.__tablename__} {entity.id}: {constraint or 'a unique key'} is taken"
                ) from error

    async def _insert(
        self,
        row_type: type[Any],
        org_id: UUID,
        entity: Identifiable,
        outbox_rows: tuple[OutboxRow, ...] = (),
        **extra: Any,
    ) -> bool:
        """The create primitive: insert by id and commit, with the outbox rows in
        the same commit; `extra` sets storage-only columns beside the entity's.
        False when the id is already written, in which case
        nothing changes, the outbox rows included. Ids are minted above storage,
        so an existing id is a retry, and a retry must neither overwrite the row
        nor announce it twice. Only the primary key reports False: any other
        unique key the row violates is `UniqueKeyTaken`, a Conflict, never a
        driver error and never mistaken for a retry."""
        if outbox_rows and role_of(row_type) is not role_of(OutboxRows):
            raise CrossRoleStatement(
                f"{row_type.__tablename__} is not in the outbox's role; no outbox row"
            )
        async with self._session_for(row_type, org_id=org_id) as session:
            session.add(to_row(entity, row_type, org_id=org_id, **extra))
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
        a unique key the read did not see is `UniqueKeyTaken` here too. A
        global table is `system`-scoped and carries no policy, so the funnel
        takes the system scope: `EMPTY_UUID`, spelled here and nowhere in a
        caller. Every caller of this primitive is in the enumerated
        exceptions, because a global row is written with no tenant in hand."""
        entity_id = entity.id
        async with self._session_for(row_type, org_id=EMPTY_UUID) as session:
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
