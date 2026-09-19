from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update

from tadas.om.exceptions import Conflict, UniqueKeyTaken
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.pg_base import PgStorageBase
from tadas.om.storage.utils.translation import to_model
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
        stmt = select(Orgs).where(Orgs.slug == slug)
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
            raise Conflict(f"identity {user.identity_id} already has a live user") from error

    async def read_memberships(self, org_id: UUID, limit: int) -> list[Membership]:
        stmt = (
            select(Memberships)
            .where(Memberships.org_id == org_id)
            .order_by(Memberships.id)
            .limit(limit)
        )
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [to_model(row, Membership) for row in result.scalars()]

    async def read_membership_for_user(self, org_id: UUID, user_id: UUID) -> Membership | None:
        stmt = select(Memberships).where(
            Memberships.org_id == org_id, Memberships.user_id == user_id
        )
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Membership)

    async def write_membership(
        self, org_id: UUID, membership: Membership, outbox_row: OutboxRow | None = None
    ) -> None:
        await self._upsert(Memberships, org_id, membership, outbox_row)

    async def read_sessions(self, org_id: UUID, user_id: UUID, limit: int) -> list[Session]:
        stmt = (
            select(Sessions)
            .where(
                Sessions.org_id == org_id,
                Sessions.user_id == user_id,
                Sessions.revoked_at.is_(None),
            )
            .order_by(Sessions.id)
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

    async def write_session(self, org_id: UUID, session: Session) -> None:
        await self._upsert(Sessions, org_id, session)

    async def read_api_keys(self, org_id: UUID, limit: int) -> list[ApiKey]:
        stmt = (
            select(ApiKeys)
            .where(ApiKeys.org_id == org_id, ApiKeys.deleted_at.is_(None))
            .order_by(ApiKeys.id)
            .limit(limit)
        )
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
            if user_ids:
                memberships = (
                    delete(Memberships)
                    .where(Memberships.org_id == org_id, Memberships.user_id.in_(user_ids))
                    .returning(Memberships.id)
                )
                purged += len((await session.execute(memberships)).scalars().all())
            keys = (
                delete(ApiKeys)
                .where(ApiKeys.org_id == org_id, ApiKeys.deleted_at < before)
                .returning(ApiKeys.id)
            )
            purged += len((await session.execute(keys)).scalars().all())
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
