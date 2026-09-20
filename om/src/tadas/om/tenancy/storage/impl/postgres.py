from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from tadas.om.base import Identifiable
from tadas.om.exceptions import Conflict, NotFound, TenantMismatch, UniqueKeyTaken
from tadas.om.outbox.storage.tables.outbox_rows import OutboxRows
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.pg_base import PgStorageBase, violated_constraint
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
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.socket_ticket import SocketTicket
from tadas.om.tenancy.types.user import User


class TenancyStoragePostgresImpl(PgStorageBase, TenancyStorageInterface):
    async def read_identity(self, identity_id: UUID) -> Identity | None:
        stmt = select(Identities).where(Identities.id == identity_id)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Identity)

    async def read_identity_by_email(self, email: str) -> Identity | None:
        stmt = select(Identities).where(Identities.email == email)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Identity)

    async def write_identity(self, identity: Identity) -> None:
        await self._upsert_global(Identities, identity)

    async def read_org(self, org_id: UUID) -> Org | None:
        stmt = select(Orgs).where(Orgs.org_id == org_id, Orgs.id == org_id)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Org)

    async def read_org_by_slug(self, slug: str) -> Org | None:
        stmt = select(Orgs).where(Orgs.slug == slug, Orgs.deleted_at.is_(None))
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Org)

    async def read_orgs(self, limit: int, after_id: UUID | None = None) -> list[Org]:
        stmt = select(Orgs).order_by(Orgs.id).limit(limit)
        if after_id is not None:
            stmt = stmt.where(Orgs.id > after_id)
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [to_model(row, Org) for row in result.scalars()]

    async def write_org(self, org_id: UUID, org: Org) -> None:
        await self._upsert(Orgs, org_id, org)

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
        outbox_row: OutboxRow,
        identity: Identity | None = None,
    ) -> None:
        await self._create_together(
            org_id,
            (Users, user),
            (Memberships, membership),
            (OutboxRows, outbox_row),
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
        async with self._session_for(row_type) as session:
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
        self, org_id: UUID, user: User, membership: Membership, outbox_row: OutboxRow
    ) -> None:
        # Two updates and the outbox row in one commit; a row that is missing
        # or another tenant's lands nothing.
        async with self._session_for(Users) as session:
            for table, entity in ((Users, user), (Memberships, membership)):
                row = await session.get(table, entity.id)
                if row is None:
                    raise NotFound(f"{table.__tablename__} {entity.id} not found")
                if row.org_id != org_id:
                    raise TenantMismatch(f"{table.__tablename__} {entity.id} is not in {org_id}")
                apply_row(row, entity)
            session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()

    async def read_users(self, org_id: UUID, limit: int) -> list[User]:
        stmt = (
            select(Users)
            .where(Users.org_id == org_id, Users.deleted_at.is_(None))
            .order_by(Users.id)
            .limit(limit)
        )
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [to_model(row, User) for row in result.scalars()]

    async def read_user(self, org_id: UUID, user_id: UUID) -> User | None:
        stmt = select(Users).where(Users.org_id == org_id, Users.id == user_id)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, User)

    async def read_users_by_identity(self, identity_id: UUID) -> list[tuple[UUID, User]]:
        stmt = (
            select(Users)
            .where(Users.identity_id == identity_id, Users.deleted_at.is_(None))
            .order_by(Users.id)
        )
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [(row.org_id, to_model(row, User)) for row in result.scalars()]

    async def write_user(
        self, org_id: UUID, user: User, outbox_row: OutboxRow | None = None
    ) -> None:
        try:
            await self._upsert(Users, org_id, user, outbox_row)
        except UniqueKeyTaken as error:
            # uq_users_org_id_identity_id_live: one live user per identity in a tenant.
            raise UniqueKeyTaken(
                f"identity {user.identity_id} already has a live user in this org"
            ) from error

    async def read_memberships(self, org_id: UUID, limit: int) -> list[Membership]:
        stmt = (
            select(Memberships)
            .where(Memberships.org_id == org_id, Memberships.deleted_at.is_(None))
            .order_by(Memberships.id)
            .limit(limit)
        )
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [to_model(row, Membership) for row in result.scalars()]

    async def read_membership_for_user(self, org_id: UUID, user_id: UUID) -> Membership | None:
        stmt = select(Memberships).where(
            Memberships.org_id == org_id,
            Memberships.user_id == user_id,
            Memberships.deleted_at.is_(None),
        )
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Membership)

    async def write_membership(
        self, org_id: UUID, membership: Membership, outbox_row: OutboxRow | None = None
    ) -> None:
        await self._upsert(Memberships, org_id, membership, outbox_row)

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
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [to_model(row, Session) for row in result.scalars()]

    async def read_session(self, org_id: UUID, session_id: UUID) -> Session | None:
        stmt = select(Sessions).where(Sessions.org_id == org_id, Sessions.id == session_id)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Session)

    async def read_session_by_token_hash(self, token_hash: str) -> tuple[UUID, Session] | None:
        stmt = select(Sessions).where(Sessions.token_hash == token_hash)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else (row.org_id, to_model(row, Session))

    async def write_session(
        self, org_id: UUID, session: Session, outbox_row: OutboxRow | None = None
    ) -> None:
        await self._upsert(Sessions, org_id, session, outbox_row)

    async def read_api_keys(
        self, org_id: UUID, limit: int, user_id: UUID | None = None
    ) -> list[ApiKey]:
        stmt = (
            select(ApiKeys)
            .where(ApiKeys.org_id == org_id, ApiKeys.deleted_at.is_(None))
            .order_by(ApiKeys.id.desc())
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(ApiKeys.user_id == user_id)
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [to_model(row, ApiKey) for row in result.scalars()]

    async def read_api_key(self, org_id: UUID, api_key_id: UUID) -> ApiKey | None:
        stmt = select(ApiKeys).where(ApiKeys.org_id == org_id, ApiKeys.id == api_key_id)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, ApiKey)

    async def read_api_key_by_hash(self, key_hash: str) -> tuple[UUID, ApiKey] | None:
        stmt = select(ApiKeys).where(ApiKeys.key_hash == key_hash)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else (row.org_id, to_model(row, ApiKey))

    async def issue_api_key(
        self, org_id: UUID, api_key: ApiKey, outbox_row: OutboxRow
    ) -> tuple[ApiKey, bool]:
        if await self._insert(ApiKeys, org_id, api_key, outbox_row):
            return api_key, True
        # The rerun: one conditional statement re-mints the secret on the issuer's row.
        stmt = (
            update(ApiKeys)
            .where(
                ApiKeys.org_id == org_id,
                ApiKeys.id == api_key.id,
                ApiKeys.user_id == api_key.user_id,
            )
            .values(
                key_hash=api_key.key_hash,
                updated_at=api_key.updated_at,
                updated_by=api_key.updated_by,
            )
            .returning(ApiKeys)
        )
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise Conflict(f"api key {api_key.id} was issued by another member")
            reissued = to_model(row, ApiKey)
            await session.commit()
            return reissued, False

    async def write_api_key(
        self, org_id: UUID, api_key: ApiKey, outbox_row: OutboxRow | None = None
    ) -> None:
        await self._upsert(ApiKeys, org_id, api_key, outbox_row)

    async def purge_deleted(self, org_id: UUID, before: datetime) -> int:
        gone_users = (
            delete(Users)
            .where(Users.org_id == org_id, Users.deleted_at < before)
            .returning(Users.id)
        )
        purged = 0
        async with self._session_for(gone_users) as session:
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
                .where(ApiKeys.org_id == org_id, ApiKeys.deleted_at < before)
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
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            consumed = (row.org_id, to_model(row, SocketTicket))
            await session.commit()
            return consumed
