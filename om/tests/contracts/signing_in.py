"""How a person signs in, in the unit suites: through the identity
provider's twin, as everywhere. The twin issues the code a browser brings
back from the hosted sign-in, and the manager's own callback finishes it.
A manager a suite builds is handed a twin of its own, and `signing_in`
remembers which, so a test names the manager and nothing else."""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from weakref import WeakKeyDictionary

from tadas.infra.cache import CacheInterface
from tadas.infra.root import InfraInterface
from tadas.integrations.identity.twin import IdentityProviderTwinImpl
from tadas.integrations.impl.configured import IntegrationsOverImpl
from tadas.om.base import new_id, utcnow
from tadas.om.billing.manager import EntitlementsInterface
from tadas.om.context import AppContext, AppType, RequestContext
from tadas.om.outbox.relay import OutboxRelayInterface
from tadas.om.root import Managers, build_managers, build_tenancy
from tadas.om.storage.root import StorageInterface
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.tenancy.impl.manager import TenancyOptions
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.types.issued import IssuedLogin

from contracts.plans import ON_TEAM

_TWINS: WeakKeyDictionary[TenancyManagerInterface, IdentityProviderTwinImpl] = WeakKeyDictionary()


def signing_in[T: TenancyManagerInterface](manager: T, twin: IdentityProviderTwinImpl) -> T:
    """Remembers the twin `manager` was built over, for `provider_login`."""
    _TWINS[manager] = twin
    return manager


def twin_of(manager: TenancyManagerInterface) -> IdentityProviderTwinImpl:
    twin = _TWINS.get(manager)
    assert twin is not None, "this manager was built over no twin; build it with `signing_in`"
    return twin


async def provider_login(
    manager: TenancyManagerInterface,
    email: str,
    name: str = "",
    rctx: RequestContext | None = None,
) -> IssuedLogin:
    """A person signs in through the twin: the login and the places it
    holds. A person nobody knew is signed up, with their personal org, named
    `name` when one is given."""
    first, _, last = name.partition(" ")
    code = twin_of(manager).issue_code(email, first_name=first or None, last_name=last or None)
    stage = rctx or RequestContext(
        request_id=new_id(), app=AppContext(type=AppType.PORTAL, version="portal@test")
    )
    return await manager.sign_in.sign_in_with_code(stage, code)


def tenancy_signing_in(
    storage: TenancyStorageInterface,
    relay: OutboxRelayInterface,
    cache: CacheInterface,
    options: TenancyOptions,
    clock: Callable[[], datetime] = utcnow,
    *,
    twin: IdentityProviderTwinImpl | None = None,
    entitlements: EntitlementsInterface = ON_TEAM,
) -> TenancyManagerInterface:
    """`build_tenancy` over a twin of its own, or the one a test holds, on
    the plan `entitlements` reads: Team unless a test names another."""
    twin = twin or IdentityProviderTwinImpl()
    return signing_in(
        build_tenancy(
            storage,
            relay,
            cache,
            options,
            clock,
            identity_provider=twin,
            entitlements=entitlements,
        ),
        twin,
    )


def managers_signing_in(
    storage: StorageInterface,
    infra: InfraInterface,
    tenancy_options: TenancyOptions | None = None,
    **options: Any,
) -> Managers:
    """`build_managers` over a twin of its own."""
    twin = IdentityProviderTwinImpl()
    managers = build_managers(
        storage, infra, tenancy_options, None, IntegrationsOverImpl(twin), **options
    )
    signing_in(managers.tenancy, twin)
    return managers
