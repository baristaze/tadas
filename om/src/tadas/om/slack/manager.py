"""The slack swimlane: the one Slack channel an org connects, the one-time
codes that connect it, and the record of what the platform posted there."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.opcontext import OpContext, RequestContext
from tadas.om.slack.types.connection import IssuedSlackLinkCode, SlackConnection, SlackPost


class SlackManagerInterface(ABC):
    @abstractmethod
    async def get_connection(self, ctx: OpContext) -> SlackConnection | None:
        """The org's connected channel, or None when it has none."""
        ...

    @abstractmethod
    async def issue_link_code(self, ctx: OpContext) -> IssuedSlackLinkCode:
        """A fresh one-time code an owner or an admin types into a Slack
        channel as `/tadas link <code>`. The code is shown once and kept as a
        digest; it expires after `code_lifetime`. Requires `MANAGE_MEMBERS`,
        since the channel then speaks for the org."""
        ...

    @abstractmethod
    async def disconnect(self, ctx: OpContext) -> SlackConnection | None:
        """Deletes the org's connection, announced; None when it had none.
        Requires `MANAGE_MEMBERS`."""
        ...

    @abstractmethod
    async def redeem_link_code(
        self,
        rctx: RequestContext,
        code: str,
        team_id: str,
        channel_id: str,
        slack_user_id: str,
    ) -> SlackConnection:
        """Platform-internal, on the request stage, like a webhook's lookup: the
        code names the org, since a Slack command arrives with no tenant. The
        code is redeemed in one conditional write, so it works once, and the
        channel becomes the org's connection, replacing the one it had, under
        the attribution of the member who issued the code. NotFound when the
        code is unknown, used, or expired; `SlackChannelTaken` when another
        org holds the channel."""
        ...

    @abstractmethod
    async def channel_context(
        self, rctx: RequestContext, team_id: str, channel_id: str
    ) -> tuple[OpContext, SlackConnection] | None:
        """Platform-internal, on the request stage: the context a command typed
        in a connected channel runs under, with the connection. It is the
        tenant's service context with the member who linked the channel as the
        attribution, the way a claimed work item keeps the person who asked
        for it. None when no org holds the channel."""
        ...

    @abstractmethod
    async def mark_broken(self, ctx: OpContext, reason: str) -> SlackConnection | None:
        """Slack refused a post for good (the channel is gone, archived, or the
        app is not in it): the connection says so, announced, until it is
        linked again. None when the org has no connection."""
        ...

    @abstractmethod
    async def read_post(self, ctx: OpContext, key: UUID) -> SlackPost | None:
        """The message the work under `key` already posted, if any."""
        ...

    @abstractmethod
    async def record_post(self, ctx: OpContext, key: UUID, channel_id: str, ts: str) -> SlackPost:
        """Records the message the work under `key` posted; a second record
        under the key returns the first."""
        ...

    @abstractmethod
    async def purge_deleted(self, ctx: OpContext) -> int:
        """The sweep, for one tenant: deleted connections, spent codes, and
        post records past the retention; every row under a tenant past its
        own retention."""
        ...
