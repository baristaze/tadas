"""The billing service: the org's plan and its usage, the processor's hosted
pages, and cancellation. The processor's inbound deliveries are the
webhooks service's."""

from abc import ABC, abstractmethod

from tadas.om.context import TenantContext
from tadas.services.api.types.billing import (
    BillingView,
    OpenPortalRequest,
    RedirectView,
    StartCheckoutRequest,
)


class BillingServiceInterface(ABC):
    @abstractmethod
    async def get_billing(self, ctx: TenantContext) -> BillingView: ...

    @abstractmethod
    async def start_checkout(
        self, ctx: TenantContext, body: StartCheckoutRequest
    ) -> RedirectView: ...

    @abstractmethod
    async def open_portal(self, ctx: TenantContext, body: OpenPortalRequest) -> RedirectView: ...

    @abstractmethod
    async def cancel(self, ctx: TenantContext) -> BillingView: ...

    @abstractmethod
    async def resume(self, ctx: TenantContext) -> BillingView: ...
