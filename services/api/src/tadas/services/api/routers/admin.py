"""Operator routes under /v1/admin/*. They take OperatorContext and cannot
reach a tenant manager because no OpContext exists on this path. A read
requires the read permission of the allowlist entry and a write the write
one; the manager decides, and a refusal is the same `not_authorized` a
viewer's write gets. The creating routes run under the operator's
idempotency record, keyed like every other creating route.

The two enrolment routes take `EnrollingOperatorCtx`, the one gate an
operator with no second factor yet passes; every other route takes
`OperatorCtx`, which refuses that operator `second_factor_not_enrolled`."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from tadas.om.tasks.types.task import TaskStatus
from tadas.services.api.gateway.admin import EnrollingOperatorCtx, OperatorCtx
from tadas.services.api.gateway.idempotency import OperatorIdem
from tadas.services.api.gateway.resolve import AdminService
from tadas.services.api.types.admin import (
    AddMemberRequest,
    ConfirmTotpRequest,
    CreateOrgRequest,
    IssuedOperatorTokenView,
    IssuedTotpSecretView,
    MintOperatorTokenRequest,
    OperatorView,
    OperatorWorkItemView,
    PlatformSizeView,
    TotpConfirmedView,
)
from tadas.services.api.types.billing import CompPlanRequest, OperatorBillingView
from tadas.services.api.types.common import LIMIT_DEFAULT
from tadas.services.api.types.events import OperatorEventView
from tadas.services.api.types.tasks import TaskPageView
from tadas.services.api.types.tenancy import OrgPageView, OrgView, UserPageView, UserView

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/me", response_model=OperatorView)
async def operator_me(admin: OperatorCtx, service: AdminService) -> OperatorView:
    """Who the plane admitted and what the entry grants; the check a skill
    makes before its first read."""
    return await service.me(admin)


@router.post("/me/totp", response_model=IssuedTotpSecretView)
async def enrol_totp(admin: EnrollingOperatorCtx, service: AdminService) -> IssuedTotpSecretView:
    """Mints the operator's TOTP secret and answers it once, as the
    `otpauth://` URI an authenticator app reads. It creates no row, and a
    retry is safe: minting again replaces a secret that was never confirmed,
    so it takes no Idempotency-Key. Refused once one is confirmed."""
    return await service.enrol_totp(admin)


@router.post("/me/totp/confirm", response_model=TotpConfirmedView)
async def confirm_totp(
    admin: EnrollingOperatorCtx, service: AdminService, body: ConfirmTotpRequest
) -> TotpConfirmedView:
    """The first code confirms the secret. From then on the plane admits
    this identity only on a sign-in that verified a code."""
    return await service.confirm_totp(admin, body)


@router.post("/me/tokens", response_model=IssuedOperatorTokenView, status_code=201)
async def mint_token(
    admin: OperatorCtx,
    service: AdminService,
    body: MintOperatorTokenRequest,
    idem: OperatorIdem,
) -> Response:
    """An operator token for an agent: one permission, never wider than the
    caller's entry, an hour at most. Minted only from a sign-in that
    verified a second factor, so a token never mints a token."""
    return await idem.run(201, lambda attempt: service.mint_token(admin, body))


@router.get("/size", response_model=PlatformSizeView)
async def platform_size(admin: OperatorCtx, service: AdminService) -> PlatformSizeView:
    return await service.size(admin)


@router.get("/orgs", response_model=OrgPageView)
async def list_orgs(
    admin: OperatorCtx,
    service: AdminService,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> OrgPageView:
    return await service.get_orgs(admin, cursor, limit)


@router.post("/orgs", response_model=OrgView, status_code=201)
async def create_org(
    admin: OperatorCtx, service: AdminService, body: CreateOrgRequest, idem: OperatorIdem
) -> Response:
    return await idem.run(201, lambda attempt: service.create_org(admin, body, attempt))


@router.get("/orgs/{org_id}", response_model=OrgView)
async def get_org(admin: OperatorCtx, service: AdminService, org_id: UUID) -> OrgView:
    return await service.get_org(admin, org_id)


@router.delete("/orgs/{org_id}", response_model=OrgView)
async def delete_org(admin: OperatorCtx, service: AdminService, org_id: UUID) -> OrgView:
    return await service.delete_org(admin, org_id)


@router.get("/orgs/{org_id}/members", response_model=UserPageView)
async def list_members(
    admin: OperatorCtx,
    service: AdminService,
    org_id: UUID,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> UserPageView:
    return await service.get_members(admin, org_id, cursor, limit)


@router.post("/orgs/{org_id}/members", response_model=UserView, status_code=201)
async def add_member(
    admin: OperatorCtx,
    service: AdminService,
    org_id: UUID,
    body: AddMemberRequest,
    idem: OperatorIdem,
) -> Response:
    return await idem.run(201, lambda attempt: service.add_member(admin, org_id, body, attempt))


@router.get("/orgs/{org_id}/tasks", response_model=TaskPageView)
async def list_tasks(
    admin: OperatorCtx,
    service: AdminService,
    org_id: UUID,
    status: TaskStatus = TaskStatus.OPEN,
    cursor: str | None = None,
    limit: int = LIMIT_DEFAULT,
) -> TaskPageView:
    return await service.get_tasks(admin, org_id, status, cursor, limit)


@router.get("/orgs/{org_id}/events", response_model=list[OperatorEventView])
async def list_events(
    admin: OperatorCtx,
    service: AdminService,
    org_id: UUID,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: int = LIMIT_DEFAULT,
) -> list[OperatorEventView]:
    return await service.get_events(admin, org_id, after_seq, limit)


@router.get("/orgs/{org_id}/billing", response_model=OperatorBillingView)
async def get_org_billing(
    admin: OperatorCtx, service: AdminService, org_id: UUID
) -> OperatorBillingView:
    return await service.get_org_billing(admin, org_id)


@router.put("/orgs/{org_id}/plan", response_model=OperatorBillingView)
async def comp_plan(
    admin: OperatorCtx, service: AdminService, org_id: UUID, body: CompPlanRequest
) -> OperatorBillingView:
    """Grants the org a plan with no payment, or takes the grant back. A put:
    the same body twice leaves the same grant."""
    return await service.comp_plan(admin, org_id, body)


@router.post("/orgs/{org_id}/work/{item_id}/requeue", response_model=OperatorWorkItemView)
async def requeue_work(
    admin: OperatorCtx, service: AdminService, org_id: UUID, item_id: UUID
) -> OperatorWorkItemView:
    """Sends one failed work item back to the queue, available now, with its
    attempts reset; the org's diary names the operator who did. Refused
    with `409 work_not_failed` for an item that is not failed, so a second
    call finds the first one's work done and says so."""
    return await service.requeue_work(admin, org_id, item_id)
