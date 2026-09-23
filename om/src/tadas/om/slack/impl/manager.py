from datetime import timedelta
from uuid import UUID

from tadas.om.base import Platform, new_id, utcnow
from tadas.om.exceptions import NotFound, SlackChannelTaken, UniqueKeyTaken
from tadas.om.opcontext import OpContext, Permission, RequestContext
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import outbox_row
from tadas.om.slack.manager import SlackManagerInterface
from tadas.om.slack.rules import code_digest, new_link_code
from tadas.om.slack.storage import SlackStorageInterface
from tadas.om.slack.types.connection import (
    IssuedSlackLinkCode,
    SlackConnection,
    SlackConnectionStatus,
    SlackLinkCode,
    SlackPost,
)
from tadas.om.tenancy import TenancyManagerInterface


class SlackOptions(Platform):
    code_lifetime: timedelta = timedelta(minutes=10)
    retention: timedelta = timedelta(days=30)


class SlackManagerImpl(SlackManagerInterface):
    def __init__(
        self,
        storage: SlackStorageInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: SlackOptions,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._relay = relay
        self._options = options

    async def get_connection(self, ctx: OpContext) -> SlackConnection | None:
        ctx.require(Permission.READ)
        return await self._storage.read_connection(ctx.org_id)

    async def issue_link_code(self, ctx: OpContext) -> IssuedSlackLinkCode:
        ctx.require(Permission.MANAGE_MEMBERS)
        now = utcnow()
        code = new_link_code()
        expires_at = now + self._options.code_lifetime
        await self._storage.create_link_code(
            ctx.org_id,
            SlackLinkCode(
                id=new_id(),
                created_at=now,
                user_id=ctx.user_id,
                code_hash=code_digest(code),
                expires_at=expires_at,
            ),
        )
        return IssuedSlackLinkCode(code=code, expires_at=expires_at)

    async def disconnect(self, ctx: OpContext) -> SlackConnection | None:
        ctx.require(Permission.MANAGE_MEMBERS)
        current = await self._storage.read_connection(ctx.org_id)
        if current is None:
            return None
        now = utcnow()
        deleted = current.model_copy(
            update={
                "deleted_at": now,
                "deleted_by": ctx.user_id,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        await self._write(ctx, deleted, "deleted")
        return deleted

    async def redeem_link_code(
        self,
        rctx: RequestContext,
        code: str,
        team_id: str,
        channel_id: str,
        slack_user_id: str,
    ) -> SlackConnection:
        redeemed = await self._storage.redeem_link_code(code_digest(code), utcnow())
        if redeemed is None:
            raise NotFound("that code is unknown, used, or expired")
        org_id, link = redeemed
        ctx = await self._tenancy.service_context(rctx, org_id, link.user_id)
        held = await self._storage.read_connection_by_channel(team_id, channel_id)
        if held is not None and held[0] != org_id:
            raise SlackChannelTaken("this channel is connected to another org")
        now = utcnow()
        current = await self._storage.read_connection(org_id)
        if current is None:
            linked = SlackConnection(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=link.user_id,
                updated_by=link.user_id,
                team_id=team_id,
                channel_id=channel_id,
                linked_by_slack_user=slack_user_id,
            )
            action = "created"
        else:
            # Relinking writes over the org's one row: the channel, the person
            # the channel acts as, and a fresh status.
            linked = current.model_copy(
                update={
                    "created_by": link.user_id,
                    "updated_at": now,
                    "updated_by": link.user_id,
                    "team_id": team_id,
                    "channel_id": channel_id,
                    "linked_by_slack_user": slack_user_id,
                    "status": SlackConnectionStatus.OK,
                    "broken_reason": None,
                }
            )
            action = "updated"
        try:
            await self._write(ctx, linked, action)
        except UniqueKeyTaken:
            # A race the read above did not see: another org took the channel.
            raise SlackChannelTaken("this channel is connected to another org") from None
        return linked

    async def channel_context(
        self, rctx: RequestContext, team_id: str, channel_id: str
    ) -> tuple[OpContext, SlackConnection] | None:
        held = await self._storage.read_connection_by_channel(team_id, channel_id)
        if held is None:
            return None
        org_id, connection = held
        ctx = await self._tenancy.service_context(rctx, org_id, connection.created_by)
        return ctx, connection

    async def mark_broken(self, ctx: OpContext, reason: str) -> SlackConnection | None:
        ctx.require(Permission.WRITE)
        current = await self._storage.read_connection(ctx.org_id)
        if current is None:
            return None
        if current.status is SlackConnectionStatus.BROKEN and current.broken_reason == reason:
            return current
        broken = current.model_copy(
            update={
                "status": SlackConnectionStatus.BROKEN,
                "broken_reason": reason,
                "updated_at": utcnow(),
                "updated_by": ctx.user_id,
            }
        )
        await self._write(ctx, broken, "updated")
        return broken

    async def read_post(self, ctx: OpContext, key: UUID) -> SlackPost | None:
        ctx.require(Permission.READ)
        return await self._storage.read_post(ctx.org_id, key)

    async def record_post(self, ctx: OpContext, key: UUID, channel_id: str, ts: str) -> SlackPost:
        ctx.require(Permission.WRITE)
        post = SlackPost(id=new_id(), created_at=utcnow(), key=key, channel_id=channel_id, ts=ts)
        if await self._storage.create_post(ctx.org_id, post):
            return post
        existing = await self._storage.read_post(ctx.org_id, key)
        if existing is None:
            raise NotFound(f"slack post {key} vanished while it was recorded")
        return existing

    async def purge_deleted(self, ctx: OpContext) -> int:
        ctx.require(Permission.WRITE)
        if await self._tenancy.tenant_expired(ctx):
            return await self._storage.purge_tenant(ctx.org_id)
        return await self._storage.purge(ctx.org_id, utcnow() - self._options.retention)

    async def _write(self, ctx: OpContext, connection: SlackConnection, action: str) -> None:
        """The connection and the row that announces it, in one commit; the
        portal's settings hear it and read the connection again. Ids only."""
        rows = (outbox_row(ctx, f"slack.connection.{action}", connection.id, {}),)
        await self._storage.write_connection(ctx.org_id, connection, rows)
        for row in rows:
            await self._relay.relay(ctx.org_id, row)
