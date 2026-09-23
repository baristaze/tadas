from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from tadas.om.base import EMPTY_UUID
from tadas.om.exceptions import UniqueKeyTaken
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.slack.storage import SlackStorageInterface
from tadas.om.slack.storage.tables.slack import SlackConnections, SlackLinkCodes, SlackPosts
from tadas.om.slack.types.connection import SlackConnection, SlackLinkCode, SlackPost
from tadas.om.storage.impl.pg_base import PgStorageBase, violated_constraint
from tadas.om.storage.utils.translation import to_model, to_row


class SlackStoragePostgresImpl(PgStorageBase, SlackStorageInterface):
    async def read_connection(self, org_id: UUID) -> SlackConnection | None:
        stmt = select(SlackConnections).where(
            SlackConnections.org_id == org_id, SlackConnections.deleted_at.is_(None)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, SlackConnection)

    async def read_connection_by_channel(
        self, team_id: str, channel_id: str
    ) -> tuple[UUID, SlackConnection] | None:
        stmt = select(SlackConnections).where(
            SlackConnections.team_id == team_id,
            SlackConnections.channel_id == channel_id,
            SlackConnections.deleted_at.is_(None),
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else (row.org_id, to_model(row, SlackConnection))

    async def write_connection(
        self, org_id: UUID, connection: SlackConnection, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        await self._upsert(SlackConnections, org_id, connection, outbox_rows)

    async def create_link_code(self, org_id: UUID, code: SlackLinkCode) -> None:
        async with self._session_for(SlackLinkCodes, org_id=org_id) as session:
            session.add(to_row(code, SlackLinkCodes, org_id=org_id))
            try:
                await session.commit()
            except IntegrityError as error:
                raise UniqueKeyTaken(
                    f"slack_link_codes {code.id}: {violated_constraint(error) or 'a key'} is taken"
                ) from error

    async def redeem_link_code(
        self, code_hash: str, now: datetime
    ) -> tuple[UUID, SlackLinkCode] | None:
        stmt = (
            update(SlackLinkCodes)
            .where(
                SlackLinkCodes.code_hash == code_hash,
                SlackLinkCodes.redeemed_at.is_(None),
                SlackLinkCodes.expires_at > now,
            )
            .values(redeemed_at=now)
            .returning(SlackLinkCodes)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            redeemed = (row.org_id, to_model(row, SlackLinkCode))
            await session.commit()
            return redeemed

    async def read_post(self, org_id: UUID, key: UUID) -> SlackPost | None:
        stmt = select(SlackPosts).where(SlackPosts.org_id == org_id, SlackPosts.key == key)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, SlackPost)

    async def create_post(self, org_id: UUID, post: SlackPost) -> bool:
        async with self._session_for(SlackPosts, org_id=org_id) as session:
            session.add(to_row(post, SlackPosts, org_id=org_id))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                if violated_constraint(error) == "uq_slack_posts_org_id_key":
                    return False
                raise UniqueKeyTaken(
                    f"slack_posts {post.id}: {violated_constraint(error) or 'a key'} is taken"
                ) from error
            return True

    async def purge(self, org_id: UUID, before: datetime) -> int:
        purged = 0
        statements = (
            delete(SlackConnections).where(
                SlackConnections.org_id == org_id, SlackConnections.deleted_at < before
            ),
            delete(SlackLinkCodes).where(
                SlackLinkCodes.org_id == org_id,
                or_(SlackLinkCodes.expires_at < before, SlackLinkCodes.redeemed_at < before),
            ),
            delete(SlackPosts).where(SlackPosts.org_id == org_id, SlackPosts.created_at < before),
        )
        for stmt in statements:
            async with self._session_for(stmt, org_id=org_id) as session:
                purged += (await session.execute(stmt)).rowcount or 0  # type: ignore[attr-defined]
                await session.commit()
        return purged

    async def purge_tenant(self, org_id: UUID) -> int:
        purged = 0
        for table in (SlackConnections, SlackLinkCodes, SlackPosts):
            stmt = delete(table).where(table.org_id == org_id)
            async with self._session_for(stmt, org_id=org_id) as session:
                purged += (await session.execute(stmt)).rowcount or 0  # type: ignore[attr-defined]
                await session.commit()
        return purged
