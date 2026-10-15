"""Billing: the org's plan and what it entitles the org to.

- **The plan.** The org's plan, where it comes from, its seats and active
  tasks against the plan's bounds, whether the latest payment failed, and
  the plans on offer; a checkout for a paid plan and the processor's own
  portal (its home, or its flow for a new payment method), each coming
  back only to a page of the portal; cancel at the period's end, and
  taking that back. Everyone in the org reads; an owner or an admin
  changes (`/v1/billing`, `/v1/billing/checkout`, `/v1/billing/portal`,
  `/v1/billing/cancel`, `/v1/billing/resume`).
- **The payment processor's deliveries.** Outside `/v1`, since their shape
  is the processor's, pinned on the endpoint it delivers to. No
  credential: the route checks the processor's signature over the body and
  its timestamp, within a five-minute window, and queues the delivery for
  the worker; one that fails the check is a 400 and nothing is queued
  (`routers/webhooks.py`, `/webhooks/stripe`).
- **The operator plane.** An org's plan, and a plan granted it with no
  payment, or the grant taken back, under the org named in the path
  (`/v1/admin/orgs/{org_id}/billing`, `/v1/admin/orgs/{org_id}/plan`).

Each function is one call into the billing service; the checkout runs
under the idempotency record."""

from uuid import UUID

from fastapi import APIRouter, Response

from tadas.services.api.gateway.admin import OperatorCtx
from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.gateway.resolve import BillingService
from tadas.services.api.types.billing import (
    BillingView,
    CompPlanRequest,
    OpenPortalRequest,
    OperatorBillingView,
    RedirectView,
    StartCheckoutRequest,
)

router = APIRouter(prefix="/billing", tags=["billing"])
operator = APIRouter(prefix="/admin", tags=["billing"])


@router.get("", response_model=BillingView)
async def get_billing(ctx: Ctx, billing: BillingService) -> BillingView:
    return await billing.get_billing(ctx)


@router.post("/checkout", response_model=RedirectView, status_code=201)
async def start_checkout(
    ctx: Ctx, billing: BillingService, body: StartCheckoutRequest, idem: Idem
) -> Response:
    """Makes the org's customer at the processor the first time, which is a
    durable row, so the route runs under the idempotency record."""
    return await idem.run(201, lambda _: billing.start_checkout(ctx, body))


@router.post("/portal", response_model=RedirectView)
async def open_portal(ctx: Ctx, billing: BillingService, body: OpenPortalRequest) -> RedirectView:
    return await billing.open_portal(ctx, body)


@router.post("/cancel", response_model=BillingView)
async def cancel(ctx: Ctx, billing: BillingService) -> BillingView:
    """The paid plan ends at its period's end; the org keeps it until then."""
    return await billing.cancel(ctx)


@router.post("/resume", response_model=BillingView)
async def resume(ctx: Ctx, billing: BillingService) -> BillingView:
    return await billing.resume(ctx)


@operator.get("/orgs/{org_id}/billing", response_model=OperatorBillingView)
async def get_org_billing(
    admin: OperatorCtx, billing: BillingService, org_id: UUID
) -> OperatorBillingView:
    return await billing.get_org_billing(admin, org_id)


@operator.put("/orgs/{org_id}/plan", response_model=OperatorBillingView)
async def comp_plan(
    admin: OperatorCtx, billing: BillingService, org_id: UUID, body: CompPlanRequest
) -> OperatorBillingView:
    """Grants the org a plan with no payment, or takes the grant back. A put:
    the same body twice leaves the same grant."""
    return await billing.comp_plan(admin, org_id, body)
