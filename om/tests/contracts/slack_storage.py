"""The slack storage contract: the connection is unique among the living per
org and per channel, a link code is redeemed once and never after it expired,
a post is recorded once per key, and every read and write is fenced by the
tenant. The cases named in `CROSS_TENANT_CASES` present another tenant's
identifier and assert that nothing is found and nothing changes."""

from datetime import timedelta
from uuid import UUID

import pytest

from contracts.racing import race
from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import TenantMismatch, UniqueKeyTaken
from tadas.om.slack.rules import code_digest, new_link_code
from tadas.om.slack.storage import SlackStorageInterface
from tadas.om.slack.types.connection import (
    SlackConnection,
    SlackConnectionStatus,
    SlackLinkCode,
    SlackPost,
)

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_link_code",
        "create_post",
        "purge",
        "purge_tenant",
        "read_connection",
        "read_post",
        "write_connection",
    }
)
"""Every method of `SlackStorageInterface` that takes a tenant has a case in
this module that presents another tenant's."""


def make_connection(channel_id: str = "C1", team_id: str = "T1") -> SlackConnection:
    now = utcnow()
    user = new_id()
    return SlackConnection(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=user,
        updated_by=user,
        team_id=team_id,
        channel_id=channel_id,
        linked_by_slack_user="U1",
    )


def make_code(code: str, *, lifetime: timedelta = timedelta(minutes=10)) -> SlackLinkCode:
    now = utcnow()
    return SlackLinkCode(
        id=new_id(),
        created_at=now,
        user_id=new_id(),
        code_hash=code_digest(code),
        expires_at=now + lifetime,
    )


def make_post(key: UUID) -> SlackPost:
    return SlackPost(id=new_id(), created_at=utcnow(), key=key, channel_id="C1", ts="1.2")


class SlackStorageContract:
    @pytest.fixture
    def storage(self) -> SlackStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_a_connection_round_trips_and_is_found_by_its_channel(
        self, storage: SlackStorageInterface
    ) -> None:
        org = new_id()
        connection = make_connection()
        await storage.write_connection(org, connection, ())
        assert await storage.read_connection(org) == connection
        assert await storage.read_connection_by_channel("T1", "C1") == (org, connection)
        assert await storage.read_connection_by_channel("T1", "C2") is None
        assert await storage.read_connection_by_channel("T2", "C1") is None

    async def test_reads_and_writes_are_fenced_by_the_tenant(
        self, storage: SlackStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        connection = make_connection()
        await storage.write_connection(org, connection, ())
        assert await storage.read_connection(other) is None
        broken = connection.model_copy(update={"status": SlackConnectionStatus.BROKEN})
        with pytest.raises(TenantMismatch):
            await storage.write_connection(other, broken, ())
        assert await storage.read_connection(org) == connection
        await storage.create_post(org, make_post(key := new_id()))
        assert await storage.read_post(other, key) is None
        assert await storage.create_post(other, make_post(key)) is True, "a key is per tenant"
        await storage.create_link_code(other, make_code(new_link_code()))

    async def test_an_org_has_one_living_connection_and_a_channel_one_org(
        self, storage: SlackStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        first = make_connection("C1")
        await storage.write_connection(org, first, ())
        with pytest.raises(UniqueKeyTaken):
            await storage.write_connection(org, make_connection("C2"), ())
        with pytest.raises(UniqueKeyTaken):
            await storage.write_connection(other, make_connection("C1"), ())
        assert await storage.read_connection(other) is None
        # Deleting frees both keys: the org links again, and so does the channel.
        now = utcnow()
        gone = first.model_copy(update={"deleted_at": now, "deleted_by": first.created_by})
        await storage.write_connection(org, gone, ())
        assert await storage.read_connection(org) is None
        again = make_connection("C1")
        await storage.write_connection(other, again, ())
        assert await storage.read_connection_by_channel("T1", "C1") == (other, again)
        await storage.write_connection(org, make_connection("C2"), ())

    async def test_a_code_is_redeemed_once(self, storage: SlackStorageInterface) -> None:
        org = new_id()
        code = new_link_code()
        link = make_code(code)
        await storage.create_link_code(org, link)
        now = utcnow()
        redeemed = await storage.redeem_link_code(code_digest(code), now)
        assert redeemed is not None
        assert redeemed[0] == org and redeemed[1].id == link.id
        assert redeemed[1].redeemed_at == now
        assert await storage.redeem_link_code(code_digest(code), now) is None
        assert await storage.redeem_link_code(code_digest(new_link_code()), now) is None

    async def test_two_redemptions_race_and_one_wins(self, storage: SlackStorageInterface) -> None:
        code = new_link_code()
        await storage.create_link_code(new_id(), make_code(code))
        now = utcnow()
        run = await race(*(storage.redeem_link_code(code_digest(code), now) for _ in range(3)))
        assert len(run.admitted) == 1, run.summary()
        assert await storage.redeem_link_code(code_digest(code), now) is None

    async def test_an_expired_code_is_refused(self, storage: SlackStorageInterface) -> None:
        code = new_link_code()
        await storage.create_link_code(new_id(), make_code(code, lifetime=timedelta(seconds=-1)))
        assert await storage.redeem_link_code(code_digest(code), utcnow()) is None

    async def test_a_code_digest_is_unique(self, storage: SlackStorageInterface) -> None:
        code = new_link_code()
        await storage.create_link_code(new_id(), make_code(code))
        with pytest.raises(UniqueKeyTaken):
            await storage.create_link_code(new_id(), make_code(code))

    async def test_a_post_is_recorded_once_per_key(self, storage: SlackStorageInterface) -> None:
        org, key = new_id(), new_id()
        first = make_post(key)
        assert await storage.create_post(org, first) is True
        assert await storage.create_post(org, make_post(key)) is False
        assert await storage.read_post(org, key) == first

    async def test_the_purge_takes_what_is_past_the_retention(
        self, storage: SlackStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        connection = make_connection()
        now = utcnow()
        await storage.write_connection(
            org, connection.model_copy(update={"deleted_at": now, "deleted_by": new_id()}), ()
        )
        await storage.create_link_code(org, make_code(new_link_code()))
        await storage.create_post(org, make_post(new_id()))
        await storage.create_post(other, make_post(new_id()))
        assert await storage.purge(org, now - timedelta(days=1)) == 0
        assert await storage.purge(other, now + timedelta(hours=1)) == 1
        assert await storage.purge(org, now + timedelta(hours=1)) == 3
        await storage.write_connection(org, make_connection(), ())
        await storage.create_post(other, make_post(new_id()))
        assert await storage.purge_tenant(org) == 1
        assert await storage.read_connection(org) is None
        assert await storage.purge_tenant(other) == 1
