from datetime import timedelta
from unittest.mock import ANY
from uuid import UUID, uuid4

import pytest

from contracts.factories import (
    make_api_key,
    make_identity,
    make_membership,
    make_org,
    make_session,
    make_socket_ticket,
    make_user,
)
from contracts.outbox_storage import claim_all
from contracts.racing import race
from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import Conflict, NotFound, RowDeleted, TenantMismatch, UniqueKeyTaken
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.types.attempt import lease_bound
from tadas.om.idempotency.types.record import IdempotencyRecord
from tadas.om.opcontext import Role
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.user import User


def make_marker(api_key: ApiKey, attempt_id: UUID) -> IdempotencyRecord:
    """The pending marker a creating request runs under, on the key's id: what
    the re-mint of a rerun is fenced on. A marker is per (tenant, user, key),
    so each attempt in a test that needs two markers carries its own key."""
    return IdempotencyRecord(
        id=new_id(),
        created_at=utcnow(),
        user_id=api_key.user_id,
        key=f"key-{attempt_id}",
        request_digest="digest",
        target_id=api_key.id,
        attempt_id=attempt_id,
    )


def make_key_row(org_id: UUID, api_key: ApiKey) -> OutboxRow:
    """The outbox row a key's create lands with; the memory outbox the root
    wires receives it, the Postgres one inserts it in the same commit."""
    return OutboxRow(
        id=new_id(),
        created_at=utcnow(),
        org_id=org_id,
        kind="tenancy.api_key.created",
        target_id=api_key.id,
        payload={"name": api_key.name},
        actor_id=api_key.user_id,
        request_id=new_id(),
        app="api",
    )


def make_user_row(org_id: UUID, user: User) -> OutboxRow:
    return OutboxRow(
        id=new_id(),
        created_at=utcnow(),
        org_id=org_id,
        kind="tenancy.user.created",
        target_id=user.id,
        payload={"display_name": user.display_name},
        actor_id=user.created_by,
        request_id=new_id(),
        app="cli",
    )


def make_session_row(org_id: UUID, session: Session) -> OutboxRow:
    """The row a revocation lands with; the snapshot never carries the token hash."""
    return OutboxRow(
        id=new_id(),
        created_at=utcnow(),
        org_id=org_id,
        kind="tenancy.session.revoked",
        target_id=session.id,
        payload={"user_id": str(session.user_id)},
        actor_id=session.user_id,
        request_id=new_id(),
        app="portal",
    )


class TenancyStorageContract:
    @pytest.fixture
    def storage(self) -> TenancyStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    @pytest.fixture
    def outbox(self) -> OutboxStorageInterface:
        """The outbox the tenancy storage lands its rows in: the one the
        Postgres impl inserts into in the same commit, the one the root handed
        the memory impl. The concrete test class wires it."""
        raise NotImplementedError("the concrete test class provides the outbox")

    @pytest.fixture
    def markers(self) -> IdempotencyStorageInterface:
        """The same markers the tenancy storage fences its re-mint on: the one
        store for the Postgres impls, the one the root handed for the memory
        ones. The concrete test class wires it."""
        raise NotImplementedError("the concrete test class provides the markers")

    async def test_org_round_trip(self, storage: TenancyStorageInterface) -> None:
        org = make_org()
        await storage.write_org(org.id, org)
        assert await storage.read_org(org.id) == org
        assert await storage.read_org_by_slug(org.slug) == org
        assert org in await storage.read_orgs(limit=1000)

    async def test_an_org_write_lands_its_outbox_row_beside_it(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        await storage.write_org(org.id, org)
        deleted = org.model_copy(update={"deleted_at": utcnow(), "deleted_by": new_id()})
        row = OutboxRow(
            id=new_id(),
            created_at=utcnow(),
            org_id=org.id,
            kind="tenancy.org.deleted",
            target_id=org.id,
            payload={"slug": org.slug},
            actor_id=new_id(),
            request_id=new_id(),
            app="portal",
        )
        await storage.write_org(org.id, deleted, (row,))
        assert await storage.read_org(org.id) == deleted
        assert await storage.read_org_by_slug(org.slug) is None

    async def test_a_write_lands_every_row_that_announces_it(
        self, storage: TenancyStorageInterface, outbox: OutboxStorageInterface
    ) -> None:
        """A write on a core entity takes the rows that announce it as a tuple,
        so they land in one statement with it. An entity change is one row; a
        write that also starts work carries a second of kind `work.<kind>`,
        because the queue is a role of its own and no statement reaches both."""
        org = make_org()
        await storage.write_org(org.id, org)
        user = make_user(make_identity().id)
        change = make_user_row(org.id, user)
        asked = change.model_copy(update={"id": new_id(), "kind": "work.noop"})
        await storage.create_member(org.id, user, make_membership(user.id), (change, asked))
        landed = [row.id for row in await claim_all(outbox) if row.target_id == user.id]
        assert sorted(landed) == sorted([change.id, asked.id])

    async def test_purge_tenant_takes_every_row_of_the_tenant_and_keeps_the_org(
        self, storage: TenancyStorageInterface
    ) -> None:
        org, other = make_org(), make_org("Other")
        await storage.write_org(org.id, org)
        await storage.write_org(other.id, other)
        for tenant in (org, other):
            user = make_user(make_identity().id)
            await storage.create_member(
                tenant.id, user, make_membership(user.id), (make_user_row(tenant.id, user),)
            )
            await storage.write_api_key(tenant.id, make_api_key(user.id, uuid4().hex))
            await storage.write_session(tenant.id, make_session(new_id(), user.id, uuid4().hex))
            await storage.write_socket_ticket(tenant.id, make_socket_ticket(user.id, uuid4().hex))
        assert await storage.purge_tenant(org.id) == 5
        assert await storage.read_users(org.id, None, limit=10) == []
        assert await storage.read_memberships(org.id, limit=10) == []
        assert await storage.read_api_keys(org.id, None, limit=10) == []
        assert await storage.read_org(org.id) == org
        assert await storage.purge_tenant(org.id) == 0
        # The other tenant is untouched.
        assert len(await storage.read_users(other.id, None, limit=10)) == 1
        assert len(await storage.read_memberships(other.id, limit=10)) == 1
        assert len(await storage.read_api_keys(other.id, None, limit=10)) == 1

    async def test_reads_are_tenant_scoped(self, storage: TenancyStorageInterface) -> None:
        org_a, org_b = make_org("A"), make_org("B")
        identity = make_identity()
        user = make_user(identity.id)
        await storage.write_user(org_a.id, user)
        assert await storage.read_user(org_a.id, user.id) == user
        assert await storage.read_user(org_b.id, user.id) is None
        assert await storage.read_users(org_b.id, None, limit=10) == []

    async def test_write_refuses_another_tenant(self, storage: TenancyStorageInterface) -> None:
        org_a, org_b = make_org("A"), make_org("B")
        user = make_user(make_identity().id)
        await storage.write_user(org_a.id, user)
        with pytest.raises(TenantMismatch):
            await storage.write_user(org_b.id, user.model_copy(update={"display_name": "Moved"}))
        assert (await storage.read_user(org_a.id, user.id)) == user

    async def test_update_by_copy_and_write(self, storage: TenancyStorageInterface) -> None:
        org = make_org()
        user = make_user(make_identity().id)
        await storage.write_user(org.id, user)
        renamed = user.model_copy(update={"display_name": "Renamed", "updated_at": utcnow()})
        await storage.write_user(org.id, renamed)
        assert await storage.read_user(org.id, user.id) == renamed

    async def test_lists_sort_by_uuid_value_and_clamp(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        users = [make_user(make_identity().id) for _ in range(3)]  # one live user per identity
        for user in reversed(users):
            await storage.write_user(org.id, user)
        listed = await storage.read_users(org.id, None, limit=10)
        assert listed == sorted(users, key=lambda u: u.id)
        assert len(await storage.read_users(org.id, None, limit=2)) == 2

    async def test_the_user_list_pages_after_a_cursor(
        self, storage: TenancyStorageInterface
    ) -> None:
        """A cursor is the id the previous page ended on, and the next page
        starts strictly after it, so every member is reachable however small
        the page is."""
        org = make_org()
        users = sorted((make_user(make_identity().id) for _ in range(5)), key=lambda u: u.id)
        for user in users:
            await storage.write_user(org.id, user)
        paged: list[User] = []
        after: UUID | None = None
        while page := await storage.read_users(org.id, after, limit=2):
            paged += page
            after = page[-1].id
        assert paged == users
        assert await storage.read_users(org.id, users[-1].id, limit=10) == []

    async def test_soft_deleted_users_are_hidden_from_lists(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        user = make_user(make_identity().id)
        await storage.write_user(org.id, user)
        gone = user.model_copy(update={"deleted_at": utcnow(), "deleted_by": user.id})
        await storage.write_user(org.id, gone)
        assert await storage.read_users(org.id, None, limit=10) == []
        assert await storage.read_user(org.id, user.id) == gone

    async def test_a_write_never_brings_a_deleted_row_back(
        self, storage: TenancyStorageInterface
    ) -> None:
        """Every update is a read, a copy, and a write of the whole entity, so
        a delete that commits between the read and the write would be undone by
        a copy still carrying `deleted_at = None`, leaving a live user with no
        live membership: listed, unable to sign in, and past every sweep. There
        is no restore in this domain, so the write is refused instead."""
        org = make_org()
        user = make_user(make_identity().id)
        await storage.write_user(org.id, user)
        held = await storage.read_user(org.id, user.id)
        assert held is not None
        gone = user.model_copy(update={"deleted_at": utcnow(), "deleted_by": user.id})
        await storage.write_user(org.id, gone)
        renamed = held.model_copy(update={"display_name": "Renamed", "updated_at": utcnow()})
        with pytest.raises(RowDeleted):
            await storage.write_user(org.id, renamed)
        assert await storage.read_user(org.id, user.id) == gone
        assert await storage.read_users(org.id, None, limit=10) == []

    async def test_one_live_user_per_identity_in_a_tenant(
        self, storage: TenancyStorageInterface
    ) -> None:
        org, other_org = make_org(), make_org("Other")
        identity = make_identity()
        user = make_user(identity.id)
        await storage.write_user(org.id, user)
        with pytest.raises(UniqueKeyTaken):
            await storage.write_user(org.id, make_user(identity.id))
        # The same identity in another tenant, and again here once the first is gone.
        await storage.write_user(other_org.id, make_user(identity.id))
        gone = user.model_copy(update={"deleted_at": utcnow(), "deleted_by": user.id})
        await storage.write_user(org.id, gone)
        await storage.write_user(org.id, make_user(identity.id))

    async def test_identity_is_global(self, storage: TenancyStorageInterface) -> None:
        identity = make_identity()
        await storage.write_identity(identity)
        assert await storage.read_identity(identity.id) == identity
        assert await storage.read_identity_by_email(identity.email) == identity
        assert await storage.read_identity_by_email("nobody@example.test") is None

    # Every unique key the schema declares has a case here, so the memory impl
    # refuses what the engine refuses: the write raises UniqueKeyTaken and the
    # row that held the key is unchanged. An update by copy of the row that
    # holds the key passes.

    async def test_identity_email_is_unique(self, storage: TenancyStorageInterface) -> None:
        email = f"{uuid4().hex}@example.test"
        identity = make_identity(email)
        await storage.write_identity(identity)
        with pytest.raises(UniqueKeyTaken):
            await storage.write_identity(make_identity(email))
        assert await storage.read_identity_by_email(email) == identity
        promoted = identity.model_copy(update={"is_operator": True})
        await storage.write_identity(promoted)
        assert await storage.read_identity(identity.id) == promoted

    async def test_org_slug_is_unique(self, storage: TenancyStorageInterface) -> None:
        org = make_org()
        await storage.write_org(org.id, org)
        other = make_org("Other").model_copy(update={"slug": org.slug})
        with pytest.raises(UniqueKeyTaken):
            await storage.write_org(other.id, other)
        assert await storage.read_org(other.id) is None
        assert await storage.read_org_by_slug(org.slug) == org
        renamed = org.model_copy(update={"name": "Renamed"})
        await storage.write_org(org.id, renamed)
        assert await storage.read_org_by_slug(org.slug) == renamed

    async def test_one_membership_per_user_in_a_tenant(
        self, storage: TenancyStorageInterface
    ) -> None:
        org, other_org = make_org(), make_org("Other")
        membership = make_membership(new_id())
        await storage.write_membership(org.id, membership)
        with pytest.raises(UniqueKeyTaken):
            await storage.write_membership(org.id, make_membership(membership.user_id))
        assert await storage.read_memberships(org.id, limit=10) == [membership]
        # The same user id in another tenant is another key.
        await storage.write_membership(other_org.id, make_membership(membership.user_id))
        promoted = membership.model_copy(update={"role": Role.ADMIN})
        await storage.write_membership(org.id, promoted)
        assert await storage.read_membership_for_user(org.id, membership.user_id) == promoted

    # A unique key on a soft-deletable table is unique among the living: a
    # deleted row frees its key, the same value is created again, and a second
    # live row is still refused.

    async def test_a_deleted_org_frees_its_slug(self, storage: TenancyStorageInterface) -> None:
        org = make_org()
        await storage.write_org(org.id, org)
        gone = org.model_copy(update={"deleted_at": utcnow(), "deleted_by": new_id()})
        await storage.write_org(org.id, gone)
        assert await storage.read_org_by_slug(org.slug) is None
        again = make_org().model_copy(update={"slug": org.slug})
        await storage.write_org(again.id, again)
        assert await storage.read_org_by_slug(org.slug) == again
        assert await storage.read_org(org.id) == gone
        other = make_org("Other").model_copy(update={"slug": org.slug})
        with pytest.raises(UniqueKeyTaken):
            await storage.write_org(other.id, other)
        assert await storage.read_org(other.id) is None

    async def test_an_ended_membership_frees_its_user(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        membership = make_membership(new_id())
        await storage.write_membership(org.id, membership)
        ended = membership.model_copy(update={"deleted_at": utcnow(), "deleted_by": new_id()})
        await storage.write_membership(org.id, ended)
        assert await storage.read_membership_for_user(org.id, membership.user_id) is None
        again = make_membership(membership.user_id)
        await storage.write_membership(org.id, again)
        assert await storage.read_membership_for_user(org.id, membership.user_id) == again
        with pytest.raises(UniqueKeyTaken):
            await storage.write_membership(org.id, make_membership(membership.user_id))
        assert await storage.read_memberships(org.id, limit=10) == [again]

    async def test_session_token_hash_is_unique(self, storage: TenancyStorageInterface) -> None:
        org, other_org = make_org(), make_org("Other")
        token_hash = uuid4().hex
        session = make_session(new_id(), new_id(), token_hash)
        await storage.write_session(org.id, session)
        with pytest.raises(UniqueKeyTaken):
            await storage.write_session(other_org.id, make_session(new_id(), new_id(), token_hash))
        assert await storage.read_session_by_token_hash(token_hash) == (org.id, session)
        revoked = session.model_copy(update={"revoked_at": utcnow()})
        await storage.write_session(org.id, revoked)
        assert await storage.read_session(org.id, session.id) == revoked

    async def test_api_key_hash_is_unique(self, storage: TenancyStorageInterface) -> None:
        org, other_org = make_org(), make_org("Other")
        key_hash = uuid4().hex
        api_key = make_api_key(new_id(), key_hash)
        await storage.write_api_key(org.id, api_key)
        with pytest.raises(UniqueKeyTaken):
            await storage.write_api_key(other_org.id, make_api_key(new_id(), key_hash))
        # The create refuses it too, and lands nothing under the new id.
        minted = make_api_key(new_id(), key_hash)
        with pytest.raises(UniqueKeyTaken):
            await storage.issue_api_key(org.id, minted, (make_key_row(org.id, minted),), None)
        assert await storage.read_api_key(org.id, minted.id) is None
        assert await storage.read_api_key_by_hash(key_hash) == (org.id, api_key)
        renamed = api_key.model_copy(update={"name": "renamed"})
        await storage.write_api_key(org.id, renamed)
        assert await storage.read_api_key(org.id, api_key.id) == renamed

    async def test_socket_ticket_hash_is_unique(self, storage: TenancyStorageInterface) -> None:
        org, other_org = make_org(), make_org("Other")
        ticket_hash = uuid4().hex
        ticket = make_socket_ticket(new_id(), ticket_hash)
        await storage.write_socket_ticket(org.id, ticket)
        with pytest.raises(UniqueKeyTaken):
            await storage.write_socket_ticket(
                other_org.id, make_socket_ticket(new_id(), ticket_hash)
            )
        redeemed_at = utcnow()
        assert await storage.consume_socket_ticket(ticket_hash, redeemed_at) == (
            org.id,
            ticket.model_copy(update={"redeemed_at": redeemed_at}),
        )

    async def test_create_org_with_owner_lands_whole_or_not_at_all(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        owner = make_user(make_identity().id)
        await storage.create_org_with_owner(
            org.id, org, owner, make_membership(owner.id, Role.OWNER)
        )
        assert await storage.read_org(org.id) == org
        assert await storage.read_user(org.id, owner.id) == owner
        assert (await storage.read_membership_for_user(org.id, owner.id)) is not None
        # The slug taken meanwhile: no org, no user, no membership of the loser.
        other = make_org("Other").model_copy(update={"slug": org.slug})
        loser = make_user(make_identity().id)
        with pytest.raises(UniqueKeyTaken):
            await storage.create_org_with_owner(
                other.id, other, loser, make_membership(loser.id, Role.OWNER)
            )
        assert await storage.read_org(other.id) is None
        assert await storage.read_user(other.id, loser.id) is None
        assert await storage.read_memberships(other.id, limit=10) == []

    async def test_create_org_with_owner_lands_the_identity_in_the_same_commit(
        self, storage: TenancyStorageInterface
    ) -> None:
        # A new identity lands with its tenant; when the slug is taken it does
        # not land at all, and an existing identity is not promoted either.
        org, identity = make_org(), make_identity()
        owner = make_user(identity.id)
        await storage.create_org_with_owner(
            org.id, org, owner, make_membership(owner.id, Role.OWNER), identity
        )
        assert await storage.read_identity(identity.id) == identity
        other = make_org("Other").model_copy(update={"slug": org.slug})
        newcomer = make_identity()
        loser = make_user(newcomer.id)
        with pytest.raises(UniqueKeyTaken):
            await storage.create_org_with_owner(
                other.id, other, loser, make_membership(loser.id, Role.OWNER), newcomer
            )
        assert await storage.read_identity(newcomer.id) is None
        promoted = identity.model_copy(update={"is_operator": True})
        again = make_user(identity.id)
        with pytest.raises(UniqueKeyTaken):
            await storage.create_org_with_owner(
                other.id, other, again, make_membership(again.id, Role.OWNER), promoted
            )
        assert await storage.read_identity(identity.id) == identity
        # From a free slug the promotion lands with the tenant.
        free = make_org("Free")
        await storage.create_org_with_owner(
            free.id, free, again, make_membership(again.id, Role.OWNER), promoted
        )
        assert await storage.read_identity(identity.id) == promoted

    async def test_create_member_lands_whole_or_not_at_all(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        identity = make_identity()
        bob = make_user(identity.id)
        await storage.create_member(
            org.id, bob, make_membership(bob.id), (make_user_row(org.id, bob),)
        )
        assert await storage.read_user(org.id, bob.id) == bob
        assert (await storage.read_membership_for_user(org.id, bob.id)) is not None
        # The same identity added again meanwhile: the user key refuses it and
        # the membership does not land either.
        again = make_user(identity.id)
        with pytest.raises(UniqueKeyTaken):
            await storage.create_member(
                org.id, again, make_membership(again.id), (make_user_row(org.id, again),)
            )
        assert await storage.read_user(org.id, again.id) is None
        assert await storage.read_membership_for_user(org.id, again.id) is None
        # A membership the user already holds: the user does not land either.
        cid = make_user(make_identity().id)
        with pytest.raises(UniqueKeyTaken):
            await storage.create_member(
                org.id, cid, make_membership(bob.id), (make_user_row(org.id, cid),)
            )
        assert await storage.read_user(org.id, cid.id) is None
        assert len(await storage.read_memberships(org.id, limit=10)) == 1
        # A new identity lands with the member, or not at all.
        newcomer = make_identity()
        dan = make_user(newcomer.id)
        with pytest.raises(UniqueKeyTaken):
            await storage.create_member(
                org.id, dan, make_membership(bob.id), (make_user_row(org.id, dan),), newcomer
            )
        assert await storage.read_identity(newcomer.id) is None
        await storage.create_member(
            org.id, dan, make_membership(dan.id), (make_user_row(org.id, dan),), newcomer
        )
        assert await storage.read_identity(newcomer.id) == newcomer
        assert await storage.read_user(org.id, dan.id) == dan

    async def test_remove_member_lands_whole_or_not_at_all(
        self, storage: TenancyStorageInterface
    ) -> None:
        org, other = make_org(), make_org("Other")
        bob = make_user(make_identity().id)
        membership = make_membership(bob.id)
        await storage.create_member(org.id, bob, membership, (make_user_row(org.id, bob),))
        gone = utcnow()
        removed = bob.model_copy(update={"deleted_at": gone, "deleted_by": bob.id})
        ended = membership.model_copy(update={"deleted_at": gone, "deleted_by": bob.id})
        # A membership that is not there, or a user of another tenant: nothing lands.
        with pytest.raises(NotFound):
            await storage.remove_member(
                org.id, removed, make_membership(bob.id), (make_user_row(org.id, bob),)
            )
        with pytest.raises((NotFound, TenantMismatch)):
            await storage.remove_member(other.id, removed, ended, (make_user_row(other.id, bob),))
        assert await storage.read_user(org.id, bob.id) == bob
        assert await storage.read_membership_for_user(org.id, bob.id) == membership
        await storage.remove_member(org.id, removed, ended, (make_user_row(org.id, bob),))
        assert await storage.read_user(org.id, bob.id) == removed
        assert await storage.read_membership_for_user(org.id, bob.id) is None
        assert await storage.read_users(org.id, None, limit=10) == []

    async def test_users_by_identity_span_tenants(self, storage: TenancyStorageInterface) -> None:
        identity = make_identity()
        org_a, org_b = make_org("A"), make_org("B")
        user_a, user_b = make_user(identity.id), make_user(identity.id)
        await storage.write_user(org_a.id, user_a)
        await storage.write_user(org_b.id, user_b)
        found = await storage.read_users_by_identity(identity.id)
        assert sorted(found, key=lambda pair: pair[1].id) == sorted(
            [(org_a.id, user_a), (org_b.id, user_b)], key=lambda pair: pair[1].id
        )

    async def test_membership_for_user(self, storage: TenancyStorageInterface) -> None:
        org = make_org()
        membership = make_membership(new_id())
        await storage.write_membership(org.id, membership)
        assert await storage.read_membership_for_user(org.id, membership.user_id) == membership
        assert await storage.read_membership_for_user(org.id, new_id()) is None
        assert await storage.read_memberships(org.id, limit=5) == [membership]

    async def test_an_ended_membership_is_hidden_from_reads_and_purged_past_retention(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        cut = utcnow()
        live, ended = make_membership(new_id()), make_membership(new_id())
        await storage.write_membership(org.id, live)
        await storage.write_membership(org.id, ended)
        await storage.write_membership(
            org.id,
            ended.model_copy(update={"deleted_at": cut - timedelta(days=1), "deleted_by": live.id}),
        )
        assert await storage.read_memberships(org.id, limit=10) == [live]
        assert await storage.read_membership_for_user(org.id, ended.user_id) is None
        assert await storage.read_membership_for_user(org.id, live.user_id) == live
        assert await storage.purge_deleted(org.id, cut) == 1  # the ended membership
        assert await storage.read_memberships(org.id, limit=10) == [live]
        assert await storage.purge_deleted(org.id, cut) == 0

    async def test_a_session_write_lands_its_outbox_row_beside_it(
        self, storage: TenancyStorageInterface
    ) -> None:
        """A revocation is a session write with a handoff: the row and its
        outbox row land together, as a user's or a key's do."""
        org = make_org()
        identity = make_identity()
        user = make_user(identity.id)
        session = make_session(
            identity.id, user.id, uuid4().hex
        )  # unique across runs of a shared database
        await storage.write_session(org.id, session)
        revoked = session.model_copy(update={"revoked_at": utcnow()})
        await storage.write_session(org.id, revoked, (make_session_row(org.id, revoked),))
        assert await storage.read_session(org.id, session.id) == revoked

    async def test_session_lookup_by_hash_returns_the_tenant(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        token_hash = uuid4().hex
        session = make_session(new_id(), new_id(), token_hash)
        await storage.write_session(org.id, session)
        assert await storage.read_session_by_token_hash(token_hash) == (org.id, session)
        assert await storage.read_session(org.id, session.id) == session
        assert await storage.read_session_by_token_hash("missing") is None

    async def test_sessions_of_a_user_are_the_live_ones_newest_first(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        identity_id, user_id = new_id(), new_id()
        now = utcnow()
        sessions = [make_session(identity_id, user_id, uuid4().hex) for _ in range(3)]
        for session in reversed(sessions):
            await storage.write_session(org.id, session)
        await storage.write_session(org.id, make_session(identity_id, new_id(), uuid4().hex))
        listed = await storage.read_sessions(org.id, user_id, now, limit=10)
        assert listed == sorted(sessions, key=lambda s: s.id, reverse=True)
        assert len(await storage.read_sessions(org.id, user_id, now, limit=2)) == 2
        revoked = sessions[0].model_copy(update={"revoked_at": now})
        await storage.write_session(org.id, revoked)
        assert revoked not in await storage.read_sessions(org.id, user_id, now, limit=10)
        assert await storage.read_session(org.id, revoked.id) == revoked
        # Expiry is the storage's filter too, before the clamp: a page of dead
        # sessions never hides a live one.
        expired = [
            make_session(identity_id, user_id, uuid4().hex, ttl=timedelta(seconds=-1))
            for _ in range(3)
        ]
        for session in expired:
            await storage.write_session(org.id, session)
        live = make_session(identity_id, user_id, uuid4().hex)
        await storage.write_session(org.id, live)
        assert await storage.read_sessions(org.id, user_id, utcnow(), limit=1) == [live]
        assert await storage.read_sessions(org.id, user_id, now - timedelta(hours=2), limit=10) == [
            live,
            *expired[::-1],
            sessions[2],
            sessions[1],
        ]

    async def test_api_keys_are_listed_newest_first_and_filtered_by_owner_before_the_clamp(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        ann, bob = new_id(), new_id()
        anns = [make_api_key(ann, uuid4().hex) for _ in range(2)]
        bobs = make_api_key(bob, uuid4().hex)
        for key in (*anns, bobs):
            await storage.write_api_key(org.id, key)
        assert await storage.read_api_keys(org.id, None, limit=10) == [bobs, anns[1], anns[0]]
        assert await storage.read_api_keys(org.id, None, limit=2) == [bobs, anns[1]]
        assert await storage.read_api_keys(org.id, None, limit=1, user_id=ann) == [anns[1]]
        assert await storage.read_api_keys(org.id, None, limit=10, user_id=bob) == [bobs]
        assert await storage.read_api_keys(org.id, None, limit=10, user_id=new_id()) == []

    async def test_the_api_key_list_pages_after_a_cursor(
        self, storage: TenancyStorageInterface
    ) -> None:
        """The key list reads newest first, so its next page is what sorts
        below the cursor; the owner filter travels with it."""
        org = make_org()
        ann = new_id()
        anns = [make_api_key(ann, uuid4().hex) for _ in range(5)]
        for key in anns:
            await storage.write_api_key(org.id, key)
        newest_first = sorted(anns, key=lambda k: k.id, reverse=True)
        paged: list[ApiKey] = []
        after: UUID | None = None
        while page := await storage.read_api_keys(org.id, after, limit=2):
            paged += page
            after = page[-1].id
        assert paged == newest_first
        assert await storage.read_api_keys(org.id, newest_first[-1].id, limit=10) == []
        assert (
            await storage.read_api_keys(org.id, newest_first[0].id, limit=2, user_id=ann)
            == (newest_first[1:3])
        )

    async def test_issue_api_key_creates_once_and_reissues_the_secret_on_a_rerun(
        self, storage: TenancyStorageInterface, markers: IdempotencyStorageInterface
    ) -> None:
        org = make_org()
        user_id = new_id()
        first_hash, second_hash = uuid4().hex, uuid4().hex
        api_key = make_api_key(user_id, first_hash)
        attempt_id = new_id()
        await markers.write_record(org.id, make_marker(api_key, attempt_id))
        assert await storage.issue_api_key(
            org.id, api_key, (make_key_row(org.id, api_key),), attempt_id
        ) == (
            api_key,
            True,
        )
        # The rerun presents the same id with a new digest, and a name and a
        # clock of its own; only the digest (and the update stamp) lands. The
        # marker still holds the attempt making it, so it is admitted.
        later = utcnow() + timedelta(seconds=1)
        rerun = api_key.model_copy(
            update={"key_hash": second_hash, "name": "renamed", "updated_at": later}
        )
        stored, created = await storage.issue_api_key(
            org.id, rerun, (make_key_row(org.id, rerun),), attempt_id
        )
        assert created is False
        assert (stored.id, stored.name, stored.created_at) == (
            api_key.id,
            api_key.name,
            api_key.created_at,
        )
        assert (stored.key_hash, stored.updated_at) == (second_hash, later)
        assert await storage.read_api_key(org.id, api_key.id) == stored
        assert await storage.read_api_key_by_hash(first_hash) is None
        assert await storage.read_api_key_by_hash(second_hash) == (org.id, stored)
        # Another issuer presenting the id is refused and changes nothing.
        other = rerun.model_copy(update={"user_id": new_id(), "key_hash": uuid4().hex})
        with pytest.raises(Conflict):
            await storage.issue_api_key(org.id, other, (make_key_row(org.id, other),), attempt_id)
        assert await storage.read_api_key(org.id, api_key.id) == stored
        # A request that carried no key holds no marker, so it never re-mints.
        keyless = rerun.model_copy(update={"key_hash": uuid4().hex})
        with pytest.raises(Conflict):
            await storage.issue_api_key(org.id, keyless, (make_key_row(org.id, keyless),), None)
        assert await storage.read_api_key(org.id, api_key.id) == stored

    async def test_a_rerun_never_re_mints_a_revoked_key(
        self, storage: TenancyStorageInterface, markers: IdempotencyStorageInterface
    ) -> None:
        """A create retried after the key was revoked must not put a live
        secret back on a dead row and answer 201 with it, marker or no
        marker."""
        org = make_org()
        user_id = new_id()
        api_key = make_api_key(user_id, uuid4().hex)
        attempt_id = new_id()
        await markers.write_record(org.id, make_marker(api_key, attempt_id))
        await storage.issue_api_key(org.id, api_key, (make_key_row(org.id, api_key),), attempt_id)
        revoked = api_key.model_copy(update={"deleted_at": utcnow(), "deleted_by": user_id})
        await storage.write_api_key(org.id, revoked)
        rerun = api_key.model_copy(update={"key_hash": uuid4().hex, "updated_at": utcnow()})
        with pytest.raises(Conflict):
            await storage.issue_api_key(org.id, rerun, (make_key_row(org.id, rerun),), attempt_id)
        assert await storage.read_api_key(org.id, api_key.id) == revoked
        assert await storage.read_api_key_by_hash(rerun.key_hash) is None

    async def test_a_rerun_never_re_mints_a_key_the_marker_no_longer_holds(
        self, storage: TenancyStorageInterface, markers: IdempotencyStorageInterface
    ) -> None:
        """An attempt that ran past the idempotency marker's pending lease is a
        zombie: the retry that took the marker over already handed its key to
        the caller, and the zombie's rerun must not overwrite it. Both attempts
        stamped the same `created_at`, which is why no ordering can tell them
        apart and only the marker can."""
        org = make_org()
        user_id = new_id()
        stalled_attempt, winning_attempt = new_id(), new_id()
        stalled = make_api_key(user_id, uuid4().hex)
        winner = stalled.model_copy(update={"key_hash": uuid4().hex})
        assert winner.created_at == stalled.created_at
        marker = make_marker(stalled, stalled_attempt)
        await markers.write_record(org.id, marker)
        # The first attempt lands the row, then stalls before its outcome.
        await storage.issue_api_key(
            org.id, stalled, (make_key_row(org.id, stalled),), stalled_attempt
        )
        # The retry takes the marker over past the lease and reruns on the same
        # id: its re-mint is admitted, and its secret is the one the caller has.
        taken = await markers.take_over_pending(
            org.id, user_id, marker.key, lease_bound(utcnow()), winning_attempt
        )
        assert taken is not None
        await storage.issue_api_key(
            org.id, winner, (make_key_row(org.id, winner),), winning_attempt
        )
        # The zombie wakes. Nothing about the two rows can be ordered; the
        # marker it no longer holds is what refuses it.
        with pytest.raises(Conflict):
            await storage.issue_api_key(
                org.id, stalled, (make_key_row(org.id, stalled),), stalled_attempt
            )
        live = await storage.read_api_key_by_hash(winner.key_hash)
        assert live is not None and live[1].id == winner.id
        assert await storage.read_api_key_by_hash(stalled.key_hash) is None

    async def test_a_rerun_whose_clock_ran_ahead_is_refused_too(
        self, storage: TenancyStorageInterface, markers: IdempotencyStorageInterface
    ) -> None:
        """The zombie's clock is ahead of the retry's, so of the two rows it is
        the one stamped later. Skew past the pending lease is what let it
        through when the fence was an ordering; the marker it lost is not."""
        org = make_org()
        user_id = new_id()
        stalled_attempt, winning_attempt = new_id(), new_id()
        winner = make_api_key(user_id, uuid4().hex)
        stalled = winner.model_copy(
            update={
                "key_hash": uuid4().hex,
                "created_at": winner.created_at + timedelta(minutes=5),
            }
        )
        marker = make_marker(stalled, stalled_attempt)
        await markers.write_record(org.id, marker)
        # The first attempt stalls before it writes anything; the retry takes
        # the marker over and lands the row and the secret the caller holds.
        taken = await markers.take_over_pending(
            org.id, user_id, marker.key, lease_bound(utcnow()), winning_attempt
        )
        assert taken is not None
        await storage.issue_api_key(
            org.id, winner, (make_key_row(org.id, winner),), winning_attempt
        )
        with pytest.raises(Conflict):
            await storage.issue_api_key(
                org.id, stalled, (make_key_row(org.id, stalled),), stalled_attempt
            )
        assert await storage.read_api_key_by_hash(winner.key_hash) == (org.id, winner)
        assert await storage.read_api_key_by_hash(stalled.key_hash) is None

    async def test_a_finished_marker_no_longer_admits_a_re_mint(
        self, storage: TenancyStorageInterface, markers: IdempotencyStorageInterface
    ) -> None:
        """The fence is the marker's liveness, not its existence: once the
        outcome is stored the secret reached the caller, and nothing re-mints
        over it."""
        org = make_org()
        user_id = new_id()
        api_key = make_api_key(user_id, uuid4().hex)
        attempt_id = new_id()
        marker = make_marker(api_key, attempt_id)
        await markers.write_record(org.id, marker)
        await storage.issue_api_key(org.id, api_key, (make_key_row(org.id, api_key),), attempt_id)
        await markers.finish_pending(org.id, user_id, marker.key, attempt_id, 201, "{}")
        rerun = api_key.model_copy(update={"key_hash": uuid4().hex, "updated_at": utcnow()})
        with pytest.raises(Conflict):
            await storage.issue_api_key(org.id, rerun, (make_key_row(org.id, rerun),), attempt_id)
        assert await storage.read_api_key_by_hash(api_key.key_hash) == (org.id, api_key)
        assert await storage.read_api_key_by_hash(rerun.key_hash) is None

    async def test_api_key_lookup_by_hash_returns_the_tenant(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        key_hash = uuid4().hex
        api_key = make_api_key(new_id(), key_hash)
        await storage.write_api_key(org.id, api_key)
        assert await storage.read_api_key_by_hash(key_hash) == (org.id, api_key)
        assert await storage.read_api_keys(org.id, None, limit=10) == [api_key]
        revoked = api_key.model_copy(update={"deleted_at": utcnow(), "deleted_by": new_id()})
        await storage.write_api_key(org.id, revoked)
        assert await storage.read_api_keys(org.id, None, limit=10) == []

    async def test_a_socket_ticket_is_consumed_by_exactly_one_redeemer(
        self, storage: TenancyStorageInterface
    ) -> None:
        # Five sockets present the one ticket. The consume is one conditional
        # write, so exactly one of them is let in. See contracts/racing.py for
        # what each impl's run of this proves.
        org = make_org()
        ticket = make_socket_ticket(new_id(), uuid4().hex)
        await storage.write_socket_ticket(org.id, ticket)
        redeemed_at = utcnow()
        run = await race(
            *(storage.consume_socket_ticket(ticket.ticket_hash, redeemed_at) for _ in range(5))
        )
        assert len(run.admitted) == 1, run.summary()
        assert run.admitted[0] == (org.id, ticket.model_copy(update={"redeemed_at": redeemed_at}))
        assert await storage.consume_socket_ticket(ticket.ticket_hash, utcnow()) is None
        assert await storage.consume_socket_ticket("missing", utcnow()) is None

    async def test_purge_removes_members_with_their_memberships_and_revoked_keys(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        await storage.write_org(org.id, org)
        cut = utcnow()
        gone, kept = make_user(make_identity().id), make_user(make_identity().id)
        await storage.write_user(
            org.id,
            gone.model_copy(update={"deleted_at": cut - timedelta(days=1), "deleted_by": gone.id}),
        )
        await storage.write_user(org.id, kept)
        await storage.write_membership(org.id, make_membership(gone.id))
        await storage.write_membership(org.id, make_membership(kept.id))
        old_key = make_api_key(kept.id, uuid4().hex).model_copy(
            update={"deleted_at": cut - timedelta(days=1), "deleted_by": kept.id}
        )
        expired_key = make_api_key(kept.id, uuid4().hex).model_copy(
            update={"expires_at": cut - timedelta(days=1)}
        )
        live_key = make_api_key(kept.id, uuid4().hex)
        await storage.write_api_key(org.id, old_key)
        await storage.write_api_key(org.id, expired_key)
        await storage.write_api_key(org.id, live_key)
        dead_sessions = [
            make_session(new_id(), kept.id, uuid4().hex).model_copy(
                update={"revoked_at": cut - timedelta(days=1)}
            ),
            make_session(new_id(), kept.id, uuid4().hex, ttl=timedelta(days=-1)),
        ]
        live_sessions = [
            make_session(new_id(), kept.id, uuid4().hex),
            make_session(new_id(), kept.id, uuid4().hex).model_copy(update={"revoked_at": cut}),
        ]
        for session in (*dead_sessions, *live_sessions):
            await storage.write_session(org.id, session)
        spent_tickets = [
            make_socket_ticket(kept.id, uuid4().hex).model_copy(
                update={"redeemed_at": cut - timedelta(days=1)}
            ),
            make_socket_ticket(kept.id, uuid4().hex, ttl=timedelta(days=-1)),
        ]
        fresh_tickets = [
            make_socket_ticket(kept.id, uuid4().hex),
            make_socket_ticket(kept.id, uuid4().hex).model_copy(update={"redeemed_at": cut}),
        ]
        for ticket in (*spent_tickets, *fresh_tickets):
            await storage.write_socket_ticket(org.id, ticket)
        # The user, its membership, two keys, two sessions, two tickets.
        assert await storage.purge_deleted(org.id, cut) == 8
        for session in dead_sessions:
            assert await storage.read_session(org.id, session.id) is None
        for session in live_sessions:
            assert await storage.read_session(org.id, session.id) == session
        for ticket in spent_tickets:
            assert await storage.consume_socket_ticket(ticket.ticket_hash, utcnow()) is None
        assert (await storage.consume_socket_ticket(fresh_tickets[0].ticket_hash, utcnow())) == (
            org.id,
            ANY,
        )
        assert await storage.read_user(org.id, gone.id) is None
        assert await storage.read_membership_for_user(org.id, gone.id) is None
        assert await storage.read_user(org.id, kept.id) == kept
        assert await storage.read_membership_for_user(org.id, kept.id) is not None
        assert await storage.read_api_key(org.id, old_key.id) is None
        assert await storage.read_api_key(org.id, expired_key.id) is None
        assert await storage.read_api_key(org.id, live_key.id) == live_key
        assert await storage.purge_deleted(org.id, cut) == 0
