"""The billing service: the org's plan and its usage, the processor's hosted
pages, and cancellation; on the operator plane, under OperatorContext, an
org's billing by its id and the plan an operator grants it. The processor's
inbound deliveries are the webhooks service's."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.context import OperatorContext, TenantContext
from tadas.services.api.types.billing import (
    BillingView,
    CompPlanRequest,
    OpenPortalRequest,
    OperatorBillingView,
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

    @abstractmethod
    async def get_org_billing(
        self, admin: OperatorContext, org_id: UUID
    ) -> OperatorBillingView: ...

    @abstractmethod
    async def comp_plan(
        self, admin: OperatorContext, org_id: UUID, body: CompPlanRequest
    ) -> OperatorBillingView: ...
