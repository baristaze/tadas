from uuid import UUID

from tadas.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.user import User


class TenancyStorageMemoryImpl(MemoryStorageBase, TenancyStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._identities: dict[UUID, Identity] = {}
        self._orgs: MemoryTable[Org] = {}
        self._users: MemoryTable[User] = {}
        self._memberships: MemoryTable[Membership] = {}
        self._sessions: MemoryTable[Session] = {}
        self._api_keys: MemoryTable[ApiKey] = {}

    async def read_identity(self, identity_id: UUID) -> Identity | None:
        return self._identities.get(identity_id)

    async def read_identity_by_email(self, email: str) -> Identity | None:
        return next((i for i in self._identities.values() if i.email == email), None)

    async def write_identity(self, identity: Identity) -> None:
        self._identities[identity.id] = identity

    async def read_org(self, org_id: UUID) -> Org | None:
        return self._get(self._orgs, org_id, org_id)

    async def read_org_by_slug(self, slug: str) -> Org | None:
        return next((org for _, org in self._orgs.values() if org.slug == slug), None)

    async def read_orgs(self, limit: int) -> list[Org]:
        return [org for _, org in self._rows_across_tenants(self._orgs)][:limit]

    async def write_org(self, org_id: UUID, org: Org) -> None:
        self._put(self._orgs, org_id, org)

    async def read_users(self, org_id: UUID, limit: int) -> list[User]:
        return [u for u in self._rows(self._users, org_id) if u.deleted_at is None][:limit]

    async def read_user(self, org_id: UUID, user_id: UUID) -> User | None:
        return self._get(self._users, org_id, user_id)

    async def read_users_by_identity(self, identity_id: UUID) -> list[tuple[UUID, User]]:
        return [
            (org_id, user)
            for org_id, user in self._rows_across_tenants(self._users)
            if user.identity_id == identity_id and user.deleted_at is None
        ]

    async def write_user(self, org_id: UUID, user: User) -> None:
        self._put(self._users, org_id, user)

    async def read_memberships(self, org_id: UUID, limit: int) -> list[Membership]:
        return self._rows(self._memberships, org_id)[:limit]

    async def read_membership_for_user(self, org_id: UUID, user_id: UUID) -> Membership | None:
        return next(
            (m for m in self._rows(self._memberships, org_id) if m.user_id == user_id), None
        )

    async def write_membership(self, org_id: UUID, membership: Membership) -> None:
        self._put(self._memberships, org_id, membership)

    async def read_sessions(self, org_id: UUID, user_id: UUID, limit: int) -> list[Session]:
        return [
            s
            for s in self._rows(self._sessions, org_id)
            if s.user_id == user_id and s.revoked_at is None
        ][:limit]

    async def read_session(self, org_id: UUID, session_id: UUID) -> Session | None:
        return self._get(self._sessions, org_id, session_id)

    async def read_session_by_token_hash(self, token_hash: str) -> tuple[UUID, Session] | None:
        return next(
            (
                (org_id, session)
                for org_id, session in self._sessions.values()
                if session.token_hash == token_hash
            ),
            None,
        )

    async def write_session(self, org_id: UUID, session: Session) -> None:
        self._put(self._sessions, org_id, session)

    async def read_api_keys(self, org_id: UUID, limit: int) -> list[ApiKey]:
        return [k for k in self._rows(self._api_keys, org_id) if k.deleted_at is None][:limit]

    async def read_api_key(self, org_id: UUID, api_key_id: UUID) -> ApiKey | None:
        return self._get(self._api_keys, org_id, api_key_id)

    async def read_api_key_by_hash(self, key_hash: str) -> tuple[UUID, ApiKey] | None:
        return next(
            ((org_id, key) for org_id, key in self._api_keys.values() if key.key_hash == key_hash),
            None,
        )

    async def write_api_key(self, org_id: UUID, api_key: ApiKey) -> None:
        self._put(self._api_keys, org_id, api_key)
