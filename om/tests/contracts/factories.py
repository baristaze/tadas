from uuid import UUID

from tadas.om.base import new_id, utcnow
from tadas.om.opcontext import CredentialKind, Role
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.socket_ticket import SocketTicket
from tadas.om.tenancy.types.user import User


def make_org(name: str = "Acme") -> Org:
    now = utcnow()
    org_id = new_id()
    return Org(
        id=org_id,
        name=name,
        created_at=now,
        updated_at=now,
        created_by=org_id,
        updated_by=org_id,
        slug=f"{name.lower()}-{org_id.hex[-12:]}",  # the random tail; the head is the millisecond
    )


def make_identity(email: str | None = None, *, operator: bool = False) -> Identity:
    now = utcnow()
    identity_id = new_id()
    return Identity(
        id=identity_id,
        created_at=now,
        updated_at=now,
        created_by=identity_id,
        updated_by=identity_id,
        email=email or f"{identity_id.hex[-12:]}@example.test",
        password_hash="scrypt$00$00",
        is_operator=operator,
    )


def make_user(identity_id: UUID, email: str = "someone@example.test") -> User:
    now = utcnow()
    user_id = new_id()
    return User(
        id=user_id,
        created_at=now,
        updated_at=now,
        created_by=user_id,
        updated_by=user_id,
        identity_id=identity_id,
        email=email,
        display_name="Someone",
    )


def make_membership(user_id: UUID, role: Role = Role.MEMBER) -> Membership:
    now = utcnow()
    return Membership(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=user_id,
        updated_by=user_id,
        user_id=user_id,
        role=role,
    )


def make_session(identity_id: UUID, user_id: UUID, token_hash: str) -> Session:
    now = utcnow()
    return Session(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=user_id,
        updated_by=user_id,
        identity_id=identity_id,
        user_id=user_id,
        token_hash=token_hash,
        credential_kind=CredentialKind.SESSION_TOKEN,
        expires_at=now,
    )


def make_api_key(user_id: UUID, key_hash: str) -> ApiKey:
    now = utcnow()
    return ApiKey(
        id=new_id(),
        name="ci",
        created_at=now,
        updated_at=now,
        created_by=user_id,
        updated_by=user_id,
        user_id=user_id,
        key_hash=key_hash,
        role=Role.MEMBER,
        expires_at=now,
    )


def make_socket_ticket(user_id: UUID, ticket_hash: str) -> SocketTicket:
    now = utcnow()
    return SocketTicket(
        id=new_id(),
        created_at=now,
        user_id=user_id,
        ticket_hash=ticket_hash,
        credential_kind=CredentialKind.SESSION_TOKEN,
        credential_id=new_id(),
        expires_at=now,
    )
