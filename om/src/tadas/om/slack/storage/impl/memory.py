from datetime import datetime
from uuid import UUID

from tadas.om.exceptions import UniqueKeyTaken
from tadas.om.outbox.storage import OutboxLandingInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.slack.storage import SlackStorageInterface
from tadas.om.slack.types.connection import SlackConnection, SlackLinkCode, SlackPost
from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class SlackStorageMemoryImpl(MemoryStorageBase, SlackStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._connections: MemoryTable[SlackConnection] = {}
        self._codes: MemoryTable[SlackLinkCode] = {}
        self._posts: MemoryTable[SlackPost] = {}

    async def read_connection(self, org_id: UUID) -> SlackConnection | None:
        living = [c for c in self._rows(self._connections, org_id) if c.deleted_at is None]
        return living[0] if living else None

    async def read_connection_by_channel(
        self, team_id: str, channel_id: str
    ) -> tuple[UUID, SlackConnection] | None:
        for org_id, connection in self._rows_across_tenants(self._connections):
            if (
                connection.deleted_at is None
                and connection.team_id == team_id
                and connection.channel_id == channel_id
            ):
                return org_id, connection
        return None

    async def write_connection(
        self, org_id: UUID, connection: SlackConnection, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        async with self._lock:
            self._fence(self._connections, org_id, connection)
            if connection.deleted_at is None:
                # The two partial unique indexes: among the living, one per org
                # and one org per channel.
                for row_org, other in self._connections.values():
                    if other.id == connection.id or other.deleted_at is not None:
                        continue
                    if row_org == org_id:
                        raise UniqueKeyTaken("uq_slack_connections_org_id is taken")
                    if (other.team_id, other.channel_id) == (
                        connection.team_id,
                        connection.channel_id,
                    ):
                        raise UniqueKeyTaken("uq_slack_connections_team_id_channel_id is taken")
            self._put(self._connections, org_id, connection, outbox_rows)

    async def create_link_code(self, org_id: UUID, code: SlackLinkCode) -> None:
        async with self._lock:
            if any(other.code_hash == code.code_hash for other in self._every(self._codes)):
                raise UniqueKeyTaken("uq_slack_link_codes_code_hash is taken")
            if not self._insert(self._codes, org_id, code):
                raise UniqueKeyTaken("pk_slack_link_codes is taken")

    async def redeem_link_code(
        self, code_hash: str, now: datetime
    ) -> tuple[UUID, SlackLinkCode] | None:
        async with self._lock:
            for org_id, code in self._rows_across_tenants(self._codes):
                if code.code_hash != code_hash:
                    continue
                if code.redeemed_at is not None or code.expires_at <= now:
                    return None
                redeemed = code.model_copy(update={"redeemed_at": now})
                self._codes[code.id] = (org_id, redeemed)
                return org_id, redeemed
            return None

    async def read_post(self, org_id: UUID, key: UUID) -> SlackPost | None:
        return next((p for p in self._rows(self._posts, org_id) if p.key == key), None)

    async def create_post(self, org_id: UUID, post: SlackPost) -> bool:
        async with self._lock:
            if any(p.key == post.key for p in self._rows(self._posts, org_id)):
                return False
            if not self._insert(self._posts, org_id, post):
                raise UniqueKeyTaken("pk_slack_posts is taken")
            return True

    async def purge(self, org_id: UUID, before: datetime) -> int:
        async with self._lock:
            gone = [
                c.id
                for c in self._rows(self._connections, org_id)
                if c.deleted_at is not None and c.deleted_at < before
            ]
            for key in gone:
                del self._connections[key]
            codes = [
                c.id
                for c in self._rows(self._codes, org_id)
                if c.expires_at < before or (c.redeemed_at is not None and c.redeemed_at < before)
            ]
            for key in codes:
                del self._codes[key]
            posts = [p.id for p in self._rows(self._posts, org_id) if p.created_at < before]
            for key in posts:
                del self._posts[key]
            return len(gone) + len(codes) + len(posts)

    async def purge_tenant(self, org_id: UUID) -> int:
        async with self._lock:
            purged = 0
            for table in (self._connections, self._codes, self._posts):
                for key in [row.id for row in self._rows(table, org_id)]:  # type: ignore[arg-type]
                    del table[key]
                    purged += 1
            return purged
