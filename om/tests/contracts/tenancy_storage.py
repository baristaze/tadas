from uuid import uuid4

import pytest

from contracts.factories import (
    make_api_key,
    make_identity,
    make_membership,
    make_org,
    make_session,
    make_user,
)
from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import TenantMismatch
from tadas.om.tenancy.storage import TenancyStorageInterface


class TenancyStorageContract:
    @pytest.fixture
    def storage(self) -> TenancyStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_org_round_trip(self, storage: TenancyStorageInterface) -> None:
        org = make_org()
        await storage.write_org(org.id, org)
        assert await storage.read_org(org.id) == org
        assert await storage.read_org_by_slug(org.slug) == org
        assert org in await storage.read_orgs(limit=1000)

    async def test_reads_are_tenant_scoped(self, storage: TenancyStorageInterface) -> None:
        org_a, org_b = make_org("A"), make_org("B")
        identity = make_identity()
        user = make_user(identity.id)
        await storage.write_user(org_a.id, user)
        assert await storage.read_user(org_a.id, user.id) == user
        assert await storage.read_user(org_b.id, user.id) is None
        assert await storage.read_users(org_b.id, limit=10) == []

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
        identity = make_identity()
        users = [make_user(identity.id) for _ in range(3)]
        for user in reversed(users):
            await storage.write_user(org.id, user)
        listed = await storage.read_users(org.id, limit=10)
        assert listed == sorted(users, key=lambda u: u.id)
        assert len(await storage.read_users(org.id, limit=2)) == 2

    async def test_soft_deleted_users_are_hidden_from_lists(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        user = make_user(make_identity().id)
        await storage.write_user(org.id, user)
        gone = user.model_copy(update={"deleted_at": utcnow(), "deleted_by": user.id})
        await storage.write_user(org.id, gone)
        assert await storage.read_users(org.id, limit=10) == []
        assert await storage.read_user(org.id, user.id) == gone

    async def test_identity_is_global(self, storage: TenancyStorageInterface) -> None:
        identity = make_identity()
        await storage.write_identity(identity)
        assert await storage.read_identity(identity.id) == identity
        assert await storage.read_identity_by_email(identity.email) == identity
        assert await storage.read_identity_by_email("nobody@example.test") is None

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

    async def test_sessions_of_a_user_hide_the_revoked_ones(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        identity_id, user_id = new_id(), new_id()
        sessions = [make_session(identity_id, user_id, uuid4().hex) for _ in range(3)]
        for session in reversed(sessions):
            await storage.write_session(org.id, session)
        await storage.write_session(org.id, make_session(identity_id, new_id(), uuid4().hex))
        listed = await storage.read_sessions(org.id, user_id, limit=10)
        assert listed == sorted(sessions, key=lambda s: s.id)
        assert len(await storage.read_sessions(org.id, user_id, limit=2)) == 2
        revoked = sessions[0].model_copy(update={"revoked_at": utcnow()})
        await storage.write_session(org.id, revoked)
        assert revoked not in await storage.read_sessions(org.id, user_id, limit=10)
        assert await storage.read_session(org.id, revoked.id) == revoked

    async def test_api_key_lookup_by_hash_returns_the_tenant(
        self, storage: TenancyStorageInterface
    ) -> None:
        org = make_org()
        key_hash = uuid4().hex
        api_key = make_api_key(new_id(), key_hash)
        await storage.write_api_key(org.id, api_key)
        assert await storage.read_api_key_by_hash(key_hash) == (org.id, api_key)
        assert await storage.read_api_keys(org.id, limit=10) == [api_key]
        revoked = api_key.model_copy(update={"deleted_at": utcnow(), "deleted_by": new_id()})
        await storage.write_api_key(org.id, revoked)
        assert await storage.read_api_keys(org.id, limit=10) == []
