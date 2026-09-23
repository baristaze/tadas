"""Doubles and helpers the manager suites share: just enough tenancy, a
context of a given role, and the media manager a tasks manager composes."""

from uuid import UUID

from contracts.factories import make_org, make_user
from tadas.infra.impl.local import InfraLocalImpl
from tadas.om.base import new_id
from tadas.om.exceptions import NotFound
from tadas.om.media.impl.manager import MediaManagerImpl, MediaOptions
from tadas.om.media.storage.impl.memory import MediaStorageMemoryImpl
from tadas.om.opcontext import (
    AppContext,
    AppType,
    CredentialKind,
    OpContext,
    RequestContext,
    Role,
    build_context,
)
from tadas.om.outbox.impl.relay import OutboxRelayImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.role import permissions_of
from tadas.om.tenancy.types.user import User

APP = AppContext(type=AppType.PORTAL, version="portal@test")


class Members(TenancyManagerInterface):
    """Just enough tenancy for the assignee check and for the sweep's question:
    the users of one org, and whether the tenant is past its retention. A
    partial double: only `get_user` and `tenant_expired` are reached, and any
    other method fails loudly as unimplemented, so the abstract set is cleared
    below."""

    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.expired = False

    async def get_user(self, ctx: OpContext, user_id: UUID) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise NotFound(f"user {user_id} not found")
        return user

    async def tenant_expired(self, ctx: OpContext) -> bool:
        return self.expired


Members.__abstractmethods__ = frozenset()


def context(role: Role, org: Org | None = None, members: Members | None = None) -> OpContext:
    user = make_user(new_id())
    if members is not None:
        members.users[user.id] = user
    return build_context(
        RequestContext(request_id=new_id(), app=APP),
        user_id=user.id,
        org_id=(org or make_org()).id,
        role=role,
        permissions=permissions_of(role),
        credential_kind=CredentialKind.SESSION_TOKEN,
    )


def media_of(
    outbox: OutboxStorageMemoryImpl,
    members: Members,
    relay: OutboxRelayImpl,
    infra: InfraLocalImpl,
) -> MediaManagerImpl:
    """The media manager a tasks manager composes, over the same outbox."""
    return MediaManagerImpl(
        MediaStorageMemoryImpl(outbox), infra.get_buckets(), members, relay, MediaOptions()
    )
