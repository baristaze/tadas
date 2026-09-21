"""The two creates the tenancy namespace has two entry points for: an org
with its owner, and a member of an org. The seeding commands (`bootstrap`,
`add-member`) reach them through the tenant manager's transitions, under a
request stage; the operator plane reaches them through the operator manager,
under an operator. Both build the same rows and land them in the same named
atomic write, so a tenant seeded from the command line and one created over
the API are indistinguishable afterwards. Nothing here constructs a stage or
decides who may call: the callers authorize, this module verifies, copies,
and writes."""

import secrets
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from tadas.infra.observability import current_traceparent
from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import Conflict, MembershipLimitReached, ValidationFailed
from tadas.om.opcontext import OperatorRole, RequestScope, Role
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import OutboxRow, snapshot
from tadas.om.tenancy.rules import hash_password
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.role import operator_permissions_of
from tadas.om.tenancy.types.user import PERSONAL_FIELDS, User

MAX_ORGS_PER_IDENTITY = 100
"""How many orgs one person may be a member of: the default of the managers'
option, which is the bound on every read of the users one identity is."""


def user_snapshot(user: User) -> Mapping[str, Any]:
    """What an event about a user records: the user without who they are."""
    return snapshot(user, exclude=PERSONAL_FIELDS)


async def users_of(
    storage: TenancyStorageInterface, identity_id: UUID, most: int
) -> list[tuple[UUID, User]]:
    """Every live user one identity is, across tenants, with the tenant. The
    read asks for one past `most`, so a list cut short is never taken for the
    whole: more than `most` (two adds that raced past the refusal below) is
    `MembershipLimitReached`, never a silent truncation that would hide the
    org a sign-in or an add is about."""
    users = await storage.read_users_by_identity(identity_id, most + 1)
    if len(users) > most:
        raise MembershipLimitReached(f"identity {identity_id} is a member of more than {most} orgs")
    return users


def refuse_one_more(identity_id: UUID, users: list[tuple[UUID, User]], most: int) -> None:
    """A create that adds a user to an identity already at `most` is refused."""
    if len(users) >= most:
        raise MembershipLimitReached(
            f"identity {identity_id} is already a member of {most} orgs, the most one may join"
        )


def widens_operator_role(identity: Identity, granted: OperatorRole) -> bool:
    """Whether granting `granted` gives the identity a permission its entry
    does not hold: a promotion, never a demotion, as the seeding reads it."""
    held = (
        frozenset()
        if identity.operator_role is None
        else operator_permissions_of(identity.operator_role)
    )
    return not operator_permissions_of(granted) <= held


async def identity_for(
    storage: TenancyStorageInterface,
    email: str,
    password: str,
    operator_role: OperatorRole | None,
    now: datetime,
) -> tuple[Identity, Identity | None]:
    """The identity as it should read once the create lands, and the row to
    write beside the create when it changed: a new identity, or an existing one
    promoted to the operator role asked for. An existing identity keeps its
    password, and a role is never narrowed. It is not written here; it lands
    in the create, so a create refused meanwhile leaves no identity carrying
    this attempt's password or role, and a retry with another password is not
    kept out."""
    identity = await storage.read_identity_by_email(email)
    if identity is None:
        identity_id = new_id()
        identity = Identity(
            id=identity_id,
            created_at=now,
            updated_at=now,
            created_by=identity_id,
            updated_by=identity_id,
            email=email,
            password_hash=hash_password(password, secrets.token_bytes(16)),
            operator_role=operator_role,
        )
        return identity, identity
    if operator_role is not None and widens_operator_role(identity, operator_role):
        identity = identity.model_copy(
            update={"operator_role": operator_role, "updated_at": now, "updated_by": identity.id}
        )
        return identity, identity
    return identity, None


async def create_org_with_owner(
    storage: TenancyStorageInterface,
    *,
    org_id: UUID,
    org_name: str,
    slug: str,
    email: str,
    password: str,
    display_name: str,
    max_orgs: int,
    operator_role: OperatorRole | None = None,
) -> tuple[Org, User, Membership]:
    """An org, its owner's user, and the owner membership, in one commit, with
    the owner's identity created or promoted beside them. A taken slug is a
    `Conflict`. The org and its rows are the owner's own: the owner is the
    first actor of the tenant, so the provenance names the owner's user."""
    if await storage.read_org_by_slug(slug) is not None:
        raise Conflict(f"org slug {slug!r} is taken")
    now = utcnow()
    identity, to_write = await identity_for(storage, email, password, operator_role, now)
    refuse_one_more(identity.id, await users_of(storage, identity.id, max_orgs), max_orgs)
    user_id = new_id()
    org = Org(
        id=org_id,
        name=org_name,
        created_at=now,
        updated_at=now,
        created_by=user_id,
        updated_by=user_id,
        slug=slug,
    )
    user = User(
        id=user_id,
        created_at=now,
        updated_at=now,
        created_by=user_id,
        updated_by=user_id,
        identity_id=identity.id,
        email=email,
        display_name=display_name,
    )
    membership = Membership(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=user_id,
        updated_by=user_id,
        user_id=user_id,
        role=Role.OWNER,
    )
    # One commit: a slug taken meanwhile leaves no org without its owner,
    # and no identity without its org.
    await storage.create_org_with_owner(org.id, org, user, membership, to_write)
    return org, user, membership


async def add_member_to(
    storage: TenancyStorageInterface,
    relay: OutboxRelayInterface,
    *,
    org_id: UUID,
    user_id: UUID,
    email: str,
    password: str,
    display_name: str,
    role: Role,
    actor_id: UUID,
    request: RequestScope,
    max_orgs: int,
) -> tuple[User, bool]:
    """A person in an org: the identity is created if the email is new (an
    existing identity keeps its password), then the user and the membership
    land with the row that announces them, in one commit, and the row is
    relayed. A person who is already a live member is returned as they are,
    with False. `actor_id` is who the rows record as their maker: the org's
    creator on the seeding path, the operator's identity on the operator plane,
    which has no user in the tenant. The service role is refused by name: it is
    the role a sweep's context carries, never a membership. A person already a
    member of `max_orgs` orgs is refused with `MembershipLimitReached`."""
    if role is Role.SERVICE:
        raise ValidationFailed("service is not a membership role")
    now = utcnow()
    identity, to_write = await identity_for(storage, email, password, None, now)
    users = await users_of(storage, identity.id, max_orgs)
    for member_org_id, existing in users:
        if member_org_id == org_id and existing.deleted_at is None:
            return existing, False
    refuse_one_more(identity.id, users, max_orgs)
    user = User(
        id=user_id,
        created_at=now,
        updated_at=now,
        created_by=actor_id,
        updated_by=actor_id,
        identity_id=identity.id,
        email=email,
        display_name=display_name,
    )
    membership = Membership(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor_id,
        updated_by=actor_id,
        user_id=user_id,
        role=role,
    )
    # One commit: the user, the membership, and the outbox row land together,
    # so a concurrent add of the same person leaves no membership without
    # its user and no user without a membership.
    row = OutboxRow(
        id=new_id(),
        created_at=now,
        org_id=org_id,
        kind="tenancy.user.created",
        target_id=user.id,
        payload=user_snapshot(user),
        actor_id=actor_id,
        request_id=request.request_id,
        traceparent=current_traceparent(),
        app=request.app.type.value,
    )
    await storage.create_member(org_id, user, membership, (row,), to_write)
    await relay.relay(org_id, row)
    return user, True
