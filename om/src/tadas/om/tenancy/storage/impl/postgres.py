from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from tadas.om.base import EMPTY_UUID, Identifiable
from tadas.om.exceptions import Conflict, NotFound, UniqueKeyTaken
from tadas.om.idempotency.storage.tables.idempotency_records import IdempotencyRecords
from tadas.om.outbox.storage.tables.outbox_rows import OutboxRows
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.pg_base import PgStorageBase, set_scope, violated_constraint
from tadas.om.storage.utils.translation import apply_row, to_model, to_row
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.tables.api_keys import ApiKeys
from tadas.om.tenancy.storage.tables.identities import Identities
from tadas.om.tenancy.storage.tables.memberships import Memberships
from tadas.om.tenancy.storage.tables.orgs import Orgs
from tadas.om.tenancy.storage.tables.sessions import Sessions
from tadas.om.tenancy.storage.tables.socket_tickets import SocketTickets
from tadas.om.tenancy.storage.tables.users import Users
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.issued import OrgMembership
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.socket_ticket import SocketTicket
from tadas.om.tenancy.types.user import User


class TenancyStoragePostgresImpl(PgStorageBase, TenancyStorageInterface):
    async def read_identity(self, identity_id: UUID) -> Identity | None:
        stmt = select(Identities).where(Identities.id == identity_id)
        async with self._session_for(stmt, EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Identity)

    async def read_identity_by_email(self, email: str) -> Identity | None:
        stmt = select(Identities).where(Identities.email == email)
        async with self._session_for(stmt, EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Identity)

    async def write_identity(self, identity: Identity) -> None:
        await self._upsert_global(Identities, identity)

    async def read_org(self, org_id: UUID) -> Org | None:
        stmt = select(Orgs).where(Orgs.org_id == org_id, Orgs.id == org_id)
        async with self._session_for(stmt, org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Org)

    async def read_org_by_slug(self, slug: str) -> Org | None:
        stmt = select(Orgs).where(Orgs.slug == slug, Orgs.deleted_at.is_(None))
        async with self._session_for(stmt, EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Org)

    async def count_orgs(self) -> int:
        stmt = select(func.count()).select_from(Orgs).where(Orgs.deleted_at.is_(None))
        async with self._session_for(stmt, EMPTY_UUID) as session:
            return (await session.execute(stmt)).scalar_one()

    async def count_users(self) -> int:
        stmt = select(func.count()).select_from(Users).where(Users.deleted_at.is_(None))
        async with self._session_for(stmt, EMPTY_UUID) as session:
            return (await session.execute(stmt)).scalar_one()

    async def read_orgs(self, limit: int, after_id: UUID | None = None) -> list[Org]:
        stmt = select(Orgs).order_by(Orgs.id).limit(limit)
        if after_id is not None:
            stmt = stmt.where(Orgs.id > after_id)
        async with self._session_for(stmt, EMPTY_UUID) as session:
            result = await session.execute(stmt)
            return [to_model(row, Org) for row in result.scalars()]

    async def write_org(
        self, org_id: UUID, org: Org, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        await self._upsert(Orgs, org_id, org, outbox_rows)

    async def create_org_with_owner(
        self,
        org_id: UUID,
        org: Org,
        user: User,
        membership: Membership,
        identity: Identity | None = None,
    ) -> None:
        await self._create_together(
            org_id, (Orgs, org), (Users, user), (Memberships, membership), identity=identity
        )

    async def create_member(
        self,
        org_id: UUID,
        user: User,
        membership: Membership,
        outbox_rows: tuple[OutboxRow, ...],
        identity: Identity | None = None,
    ) -> None:
        await self._create_together(
            org_id,
            (Users, user),
            (Memberships, membership),
            *((OutboxRows, row) for row in outbox_rows),
            identity=identity,
        )

    async def _create_together(
        self,
        org_id: UUID,
        *rows: tuple[type[Any], Identifiable],
        identity: Identity | None = None,
    ) -> None:
        """The rows land in one commit or not at all; every table is in the
        core role, which the session's role routing holds. The identity, when
        given, is written in the same commit: inserted when new, updated when
        it exists (the global table has no tenant to check). A violated key is
        UniqueKeyTaken, never a driver error."""
        row_type = rows[0][0]
        async with self._session_for(row_type, org_id) as session:
            if identity is not None:
                existing = await session.get(Identities, identity.id)
                if existing is None:
                    session.add(to_row(identity, Identities))
                else:
                    apply_row(existing, identity)
            for table, entity in rows:
                session.add(to_row(entity, table, org_id=org_id))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise UniqueKeyTaken(
                    f"{row_type.__tablename__} and its siblings: "
                    f"{violated_constraint(error) or 'a unique key'} is taken"
                ) from error

    async def remove_member(
        self, org_id: UUID, user: User, membership: Membership, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        # Two updates and the outbox rows in one commit; a row that is missing
        # or another tenant's lands nothing. Both answer the same way: a
        # caller holding an id of another tenant is told what a caller
        # holding an id that never existed is told, so the answer carries no
        # word about whether the row is out there under someone else.
        async with self._session_for(Users, org_id) as session:
            for table, entity in ((Users, user), (Memberships, membership)):
                row = await session.get(table, entity.id)
                if row is None or row.org_id != org_id:
                    raise NotFound(f"{table.__tablename__} {entity.id} is not in {org_id}")
                apply_row(row, entity)
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()

    async def read_users(self, org_id: UUID, after: UUID | None, limit: int) -> list[User]:
        stmt = (
            select(Users)
            .where(Users.org_id == org_id, Users.deleted_at.is_(None))
            .order_by(Users.id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(Users.id > after)  # is_after_in_id_order
        async with self._session_for(stmt, org_id) as session:
            result = await session.execute(stmt)
            return [to_model(row, User) for row in result.scalars()]

    async def read_user(self, org_id: UUID, user_id: UUID) -> User | None:
        stmt = select(Users).where(Users.org_id == org_id, Users.id == user_id)
        async with self._session_for(stmt, org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, User)

    async def read_users_by_identity(
        self, identity_id: UUID, limit: int
    ) -> list[tuple[UUID, User]]:
        stmt = (
            select(Users)
            .where(Users.identity_id == identity_id, Users.deleted_at.is_(None))
            .order_by(Users.id)
            .limit(limit)
        )
        async with self._session_for(stmt, EMPTY_UUID) as session:
            result = await session.execute(stmt)
            return [(row.org_id, to_model(row, User)) for row in result.scalars()]

    async def read_memberships_by_identity(
        self, identity_id: UUID, limit: int, after_user_id: UUID | None = None
    ) -> list[OrgMembership]:
        # One statement over three tables of the core role, the living only,
        # so the bound cuts the rows the caller keeps.
        stmt = (
            select(Users, Orgs, Memberships)
            .join(Orgs, (Orgs.org_id == Users.org_id) & (Orgs.id == Users.org_id))
            .join(
                Memberships,
                (Memberships.org_id == Users.org_id) & (Memberships.user_id == Users.id),
            )
            .where(
                Users.identity_id == identity_id,
                Users.deleted_at.is_(None),
                Orgs.deleted_at.is_(None),
                Memberships.deleted_at.is_(None),
            )
            .order_by(Users.id)
            .limit(limit)
        )
        if after_user_id is not None:
            stmt = stmt.where(Users.id > after_user_id)  # is_after_in_id_order
        async with self._session_for(stmt, EMPTY_UUID) as session:
            result = await session.execute(stmt)
            return [
                OrgMembership(
                    org=to_model(org, Org),
                    user=to_model(user, User),
                    role=to_model(membership, Membership).role,
                )
                for user, org, membership in result.tuples()
            ]

    async def write_user(
        self, org_id: UUID, user: User, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        try:
            await self._upsert(Users, org_id, user, outbox_rows)
        except UniqueKeyTaken as error:
            # uq_users_org_id_identity_id_live: one live user per identity in a tenant.
            raise UniqueKeyTaken(
                f"identity {user.identity_id} already has a live user in this org"
            ) from error

    async def read_memberships(
        self, org_id: UUID, limit: int, after_user_id: UUID | None = None
    ) -> list[Membership]:
        # uq_memberships_org_id_user_id covers the live rows in this order.
        stmt = (
            select(Memberships)
            .where(Memberships.org_id == org_id, Memberships.deleted_at.is_(None))
            .order_by(Memberships.user_id)
            .limit(limit)
        )
        if after_user_id is not None:
            stmt = stmt.where(Memberships.user_id > after_user_id)  # is_after_in_id_order
        async with self._session_for(stmt, org_id) as session:
            result = await session.execute(stmt)
            return [to_model(row, Membership) for row in result.scalars()]

    async def read_membership_for_user(self, org_id: UUID, user_id: UUID) -> Membership | None:
        stmt = select(Memberships).where(
            Memberships.org_id == org_id,
            Memberships.user_id == user_id,
            Memberships.deleted_at.is_(None),
        )
        async with self._session_for(stmt, org_id, user_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Membership)

    async def write_membership(
        self, org_id: UUID, membership: Membership, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        await self._upsert(Memberships, org_id, membership, outbox_rows)

    async def read_sessions(
        self, org_id: UUID, user_id: UUID, live_at: datetime, limit: int
    ) -> list[Session]:
        stmt = (
            select(Sessions)
            .where(
                Sessions.org_id == org_id,
                Sessions.user_id == user_id,
                Sessions.revoked_at.is_(None),
                Sessions.expires_at > live_at,
            )
            .order_by(Sessions.id.desc())
            .limit(limit)
        )
        async with self._session_for(stmt, org_id, user_id) as session:
            result = await session.execute(stmt)
            return [to_model(row, Session) for row in result.scalars()]

    async def read_session(self, org_id: UUID, session_id: UUID) -> Session | None:
        stmt = select(Sessions).where(Sessions.org_id == org_id, Sessions.id == session_id)
        async with self._session_for(stmt, org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Session)

    async def read_session_by_token_hash(self, token_hash: str) -> tuple[UUID, Session] | None:
        stmt = select(Sessions).where(Sessions.token_hash == token_hash)
        async with self._session_for(stmt, EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else (row.org_id, to_model(row, Session))

    async def read_session_by_id(self, session_id: UUID) -> tuple[UUID, Session] | None:
        stmt = select(Sessions).where(Sessions.id == session_id)
        async with self._session_for(stmt, EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else (row.org_id, to_model(row, Session))

    async def write_session(
        self, org_id: UUID, session: Session, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        await self._upsert(Sessions, org_id, session, outbox_rows)

    async def replace_session(
        self,
        org_id: UUID,
        session: Session,
        ended_org_id: UUID,
        ended: Session,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        # One transaction, two tenants, and never the system scope: the ended
        # session is revoked under its own tenant, then the scope is set again
        # to the new session's tenant for its insert, so each statement is
        # fenced by the tenant it touches. The row lock makes a second switch
        # on the same session wait and then find it ended.
        async with self._session_for(Sessions, ended_org_id) as db:
            row = await db.get(Sessions, ended.id, with_for_update=True)
            if row is None or row.org_id != ended_org_id:
                raise NotFound(f"session {ended.id} is not in {ended_org_id}")
            if row.revoked_at is not None:
                raise Conflict(f"session {ended.id} has already ended")
            apply_row(row, ended)
            for outbox_row in outbox_rows:
                db.add(to_row(outbox_row, OutboxRows, org_id=ended_org_id))
            try:
                await db.flush()
                await set_scope(db, org_id, None, None)
                db.add(to_row(session, Sessions, org_id=org_id))
                await db.commit()
            except IntegrityError as error:
                await db.rollback()
                taken = violated_constraint(error) or "a unique key"
                raise UniqueKeyTaken(f"sessions {session.id}: {taken} is taken") from error

    async def read_api_keys(
        self, org_id: UUID, after: UUID | None, limit: int, user_id: UUID | None = None
    ) -> list[ApiKey]:
        stmt = (
            select(ApiKeys)
            .where(ApiKeys.org_id == org_id, ApiKeys.deleted_at.is_(None))
            .order_by(ApiKeys.id.desc())
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(ApiKeys.user_id == user_id)
        if after is not None:
            stmt = stmt.where(ApiKeys.id < after)  # is_after_newest_first
        async with self._session_for(stmt, org_id, user_id) as session:
            result = await session.execute(stmt)
            return [to_model(row, ApiKey) for row in result.scalars()]

    async def read_api_key(self, org_id: UUID, api_key_id: UUID) -> ApiKey | None:
        stmt = select(ApiKeys).where(ApiKeys.org_id == org_id, ApiKeys.id == api_key_id)
        async with self._session_for(stmt, org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, ApiKey)

    async def read_api_key_by_hash(self, key_hash: str) -> tuple[UUID, ApiKey] | None:
        stmt = select(ApiKeys).where(ApiKeys.key_hash == key_hash)
        async with self._session_for(stmt, EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else (row.org_id, to_model(row, ApiKey))

    async def issue_api_key(
        self,
        org_id: UUID,
        api_key: ApiKey,
        outbox_rows: tuple[OutboxRow, ...],
        attempt_id: UUID | None,
    ) -> tuple[ApiKey, bool]:
        if await self._insert(ApiKeys, org_id, api_key, outbox_rows):
            return api_key, True
        if attempt_id is None:
            # No key, no marker, nothing holding this attempt: nothing to fence
            # the re-mint with, so there is no re-mint.
            raise Conflict(f"api key {api_key.id} cannot be re-minted")
        # The rerun: one conditional statement re-mints the secret on the
        # issuer's row, with both fences of the interface in its own WHERE. The
        # second reads the marker; both tables are in the `core` role, so the
        # statement stays inside one role and one commit.
        held = (
            select(IdempotencyRecords.id)
            .where(
                IdempotencyRecords.org_id == org_id,
                IdempotencyRecords.target_id == api_key.id,
                IdempotencyRecords.attempt_id == attempt_id,
                IdempotencyRecords.status.is_(None),
            )
            .exists()
        )
        stmt = (
            update(ApiKeys)
            .where(
                ApiKeys.org_id == org_id,
                ApiKeys.id == api_key.id,
                ApiKeys.user_id == api_key.user_id,
                ApiKeys.deleted_at.is_(None),
                held,
            )
            .values(
                key_hash=api_key.key_hash,
                updated_at=api_key.updated_at,
                updated_by=api_key.updated_by,
            )
            .returning(ApiKeys)
        )
        async with self._session_for(stmt, org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise Conflict(f"api key {api_key.id} cannot be re-minted")
            reissued = to_model(row, ApiKey)
            await session.commit()
            return reissued, False

    async def write_api_key(
        self, org_id: UUID, api_key: ApiKey, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        await self._upsert(ApiKeys, org_id, api_key, outbox_rows)

    async def purge_deleted(self, org_id: UUID, before: datetime) -> int:
        gone_users = (
            delete(Users)
            .where(Users.org_id == org_id, Users.deleted_at < before)
            .returning(Users.id)
        )
        purged = 0
        async with self._session_for(gone_users, org_id) as session:
            user_ids = list((await session.execute(gone_users)).scalars().all())
            purged += len(user_ids)
            memberships = (
                delete(Memberships)
                .where(
                    Memberships.org_id == org_id,
                    or_(Memberships.user_id.in_(user_ids), Memberships.deleted_at < before),
                )
                .returning(Memberships.id)
            )
            purged += len((await session.execute(memberships)).scalars().all())
            keys = (
                delete(ApiKeys)
                .where(
                    ApiKeys.org_id == org_id,
                    or_(ApiKeys.deleted_at < before, ApiKeys.expires_at < before),
                )
                .returning(ApiKeys.id)
            )
            purged += len((await session.execute(keys)).scalars().all())
            sessions = (
                delete(Sessions)
                .where(
                    Sessions.org_id == org_id,
                    or_(Sessions.revoked_at < before, Sessions.expires_at < before),
                )
                .returning(Sessions.id)
            )
            purged += len((await session.execute(sessions)).scalars().all())
            tickets = (
                delete(SocketTickets)
                .where(
                    SocketTickets.org_id == org_id,
                    or_(SocketTickets.redeemed_at < before, SocketTickets.expires_at < before),
                )
                .returning(SocketTickets.id)
            )
            purged += len((await session.execute(tickets)).scalars().all())
            await session.commit()
        return purged

    async def purge_tenant(self, org_id: UUID) -> int:
        purged = 0
        async with self._session_for(Users, org_id) as session:
            for table in (Users, Memberships, ApiKeys, Sessions, SocketTickets):
                stmt = delete(table).where(table.org_id == org_id).returning(table.id)
                purged += len((await session.execute(stmt)).scalars().all())
            await session.commit()
        return purged

    async def write_socket_ticket(self, org_id: UUID, ticket: SocketTicket) -> None:
        await self._upsert(SocketTickets, org_id, ticket)

    async def consume_socket_ticket(
        self, ticket_hash: str, redeemed_at: datetime
    ) -> tuple[UUID, SocketTicket] | None:
        stmt = (
            update(SocketTickets)
            .where(SocketTickets.ticket_hash == ticket_hash, SocketTickets.redeemed_at.is_(None))
            .values(redeemed_at=redeemed_at)
            .returning(SocketTickets)
        )
        async with self._session_for(stmt, EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            consumed = (row.org_id, to_model(row, SocketTicket))
            await session.commit()
            return consumed
