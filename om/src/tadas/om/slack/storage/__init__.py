"""Storage of the slack namespace: the org's connection, the link codes, and
the record of what was posted. Every operation takes org_id first, except the
two lookups that find a tenant from what Slack sends, which are cross-tenant
by nature and read in the system scope."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from tadas.om.outbox.types.row import OutboxRow
from tadas.om.slack.types.connection import SlackConnection, SlackLinkCode, SlackPost


class SlackStorageInterface(ABC):
    @abstractmethod
    async def read_connection(self, org_id: UUID) -> SlackConnection | None:
        """The org's living connection; a deleted one reads as None."""
        ...

    @abstractmethod
    async def read_connection_by_channel(
        self, team_id: str, channel_id: str
    ) -> tuple[UUID, SlackConnection] | None:
        """Cross-tenant, in the system scope: the living connection of a Slack
        channel and the org it belongs to. A command arrives with a channel and
        no tenant; this is how it finds one."""
        ...

    @abstractmethod
    async def write_connection(
        self, org_id: UUID, connection: SlackConnection, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        """Insert or update by id, with the rows that announce it in the same
        commit. A second living connection for the org, or a channel another
        living connection holds, is `UniqueKeyTaken`, and nothing lands."""
        ...

    @abstractmethod
    async def create_link_code(self, org_id: UUID, code: SlackLinkCode) -> None:
        """Lands a fresh code. Its digest is unique."""
        ...

    @abstractmethod
    async def redeem_link_code(
        self, code_hash: str, now: datetime
    ) -> tuple[UUID, SlackLinkCode] | None:
        """Cross-tenant, in the system scope, one conditional write: stamps
        `redeemed_at` on the code with this digest while it is unredeemed and
        not expired at `now`, and returns it with its org. None when there is
        no such code, it was redeemed, or it expired: a code works once."""
        ...

    @abstractmethod
    async def read_post(self, org_id: UUID, key: UUID) -> SlackPost | None:
        """The message the work under this key posted, if it did."""
        ...

    @abstractmethod
    async def create_post(self, org_id: UUID, post: SlackPost) -> bool:
        """Records a posted message; False when its key is already recorded,
        which changes nothing. The key is unique per org."""
        ...

    @abstractmethod
    async def purge(self, org_id: UUID, before: datetime) -> int:
        """The sweep's hard delete for one tenant: connections deleted, codes
        expired, and posts recorded before `before`; returns how many rows
        went."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID) -> int:
        """Every row of a deleted tenant once its retention has passed."""
        ...
