"""Storage of the tenancy swimlane. Every operation takes `org_id` first
except the ones documented below, which are global by nature or cross
tenants on purpose; the exceptions test enumerates them."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from tadas.om.outbox.types.row import OutboxRow
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.socket_ticket import SocketTicket
from tadas.om.tenancy.types.user import User


class TenancyStorageInterface(ABC):
    # Identities are global: a person exists before and across tenants.
    @abstractmethod
    async def read_identity(self, identity_id: UUID) -> Identity | None:
        """Global table: identities have no tenant."""
        ...

    @abstractmethod
    async def read_identity_by_email(self, email: str) -> Identity | None:
        """Global table: identities have no tenant."""
        ...

    @abstractmethod
    async def write_identity(self, identity: Identity) -> None:
        """Global table: identities have no tenant."""
        ...

    # Orgs are the tenants; their own id is their org_id.
    @abstractmethod
    async def read_org(self, org_id: UUID) -> Org | None: ...

    @abstractmethod
    async def read_org_by_slug(self, slug: str) -> Org | None:
        """Cross-tenant lookup: the slug is resolved before a tenant is known."""
        ...

    @abstractmethod
    async def read_orgs(self, limit: int, after_id: UUID | None = None) -> list[Org]:
        """Cross-tenant sweep: every tenant, for the operator plane and for sweeps,
        in id order; `after_id` pages, so a sweep reaches every tenant and not
        only the first clamp of them."""
        ...

    @abstractmethod
    async def write_org(self, org_id: UUID, org: Org) -> None: ...

    @abstractmethod
    async def read_users(self, org_id: UUID, limit: int) -> list[User]: ...

    @abstractmethod
    async def read_user(self, org_id: UUID, user_id: UUID) -> User | None: ...

    @abstractmethod
    async def read_users_by_identity(self, identity_id: UUID) -> list[tuple[UUID, User]]:
        """Cross-tenant sweep: the users one identity is, in every tenant, with the tenant."""
        ...

    @abstractmethod
    async def write_user(
        self, org_id: UUID, user: User, outbox_row: OutboxRow | None = None
    ) -> None:
        """Lands the row and its outbox row together; so do the other writes below."""
        ...

    @abstractmethod
    async def read_memberships(self, org_id: UUID, limit: int) -> list[Membership]: ...

    @abstractmethod
    async def read_membership_for_user(self, org_id: UUID, user_id: UUID) -> Membership | None: ...

    @abstractmethod
    async def write_membership(
        self, org_id: UUID, membership: Membership, outbox_row: OutboxRow | None = None
    ) -> None: ...

    @abstractmethod
    async def read_sessions(self, org_id: UUID, user_id: UUID, limit: int) -> list[Session]:
        """One user's sessions that are not revoked, sorted by id."""
        ...

    @abstractmethod
    async def read_session(self, org_id: UUID, session_id: UUID) -> Session | None: ...

    @abstractmethod
    async def read_session_by_token_hash(self, token_hash: str) -> tuple[UUID, Session] | None:
        """Cross-tenant lookup: the gateway holds a token, not a tenant; the tenant travels back."""
        ...

    @abstractmethod
    async def write_session(self, org_id: UUID, session: Session) -> None: ...

    @abstractmethod
    async def read_api_keys(self, org_id: UUID, limit: int) -> list[ApiKey]: ...

    @abstractmethod
    async def read_api_key(self, org_id: UUID, api_key_id: UUID) -> ApiKey | None: ...

    @abstractmethod
    async def read_api_key_by_hash(self, key_hash: str) -> tuple[UUID, ApiKey] | None:
        """Cross-tenant lookup: the gateway holds a key, not a tenant; the tenant travels back."""
        ...

    @abstractmethod
    async def write_api_key(
        self, org_id: UUID, api_key: ApiKey, outbox_row: OutboxRow | None = None
    ) -> None: ...

    @abstractmethod
    async def purge_deleted(self, org_id: UUID, before: datetime) -> int:
        """The one hard delete: removes the tenant's users soft-deleted before `before`
        with their memberships, and its api keys revoked before `before`; returns
        how many rows went."""
        ...

    @abstractmethod
    async def write_socket_ticket(self, org_id: UUID, ticket: SocketTicket) -> None: ...

    @abstractmethod
    async def consume_socket_ticket(
        self, ticket_hash: str, redeemed_at: datetime
    ) -> tuple[UUID, SocketTicket] | None:
        """Cross-tenant lookup: the gateway holds a ticket, not a tenant; the tenant
        travels back. One statement: marks the unredeemed ticket with this hash
        redeemed and returns it, or None when it is unknown or already redeemed.
        Two concurrent redeemers never both get it."""
        ...
