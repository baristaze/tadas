"""Doubles and helpers the manager suites share: just enough tenancy, a
context of a given role, and the media manager over the memory storage."""

from tadas.infra.impl.local import InfraLocalImpl
from tadas.om.base import new_id
from tadas.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    RequestContext,
    Role,
    TenantContext,
    build_context,
)
from tadas.om.media.impl.manager import MediaManagerImpl, MediaOptions
from tadas.om.media.storage.impl.memory import MediaStorageMemoryImpl
from tadas.om.outbox.impl.relay import OutboxRelayImpl
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.tenancy.rules import permissions_of
from tadas.om.tenancy.types.org import Org
from contracts.factories import make_org, make_user

APP = AppContext(type=AppType.PORTAL, version="portal@test")


class Members(TenancyManagerInterface):
    """Just enough tenancy for the sweep's question: whether the tenant is
    past its retention. A partial double: only `tenant_expired` is reached,
    and any other method fails loudly as unimplemented, so the abstract set
    is cleared below."""

    def __init__(self) -> None:
        self.expired = False

    async def tenant_expired(self, ctx: TenantContext) -> bool:
        return self.expired


Members.__abstractmethods__ = frozenset()


def context(role: Role, org: Org | None = None) -> TenantContext:
    user = make_user(new_id())
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
    """The media manager over the memory storage, landing in the same outbox."""
    return MediaManagerImpl(
        MediaStorageMemoryImpl(outbox), infra.get_buckets(), members, relay, MediaOptions()
    )
