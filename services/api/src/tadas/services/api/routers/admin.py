"""Operator routes under /v1/admin/*. They take OperatorContext and cannot
reach a tenant manager because no OpContext exists on this path. A read
requires the read permission of the allowlist entry and a write the write
one; the manager decides, and a refusal is the same `not_authorized` a
viewer's write gets. The creating routes run under the operator's
idempotency record, keyed like every other creating route."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from tadas.om.tasks.types.task import TaskStatus
from tadas.services.api.gateway.admin import OperatorCtx
from tadas.services.api.gateway.idempotency import OperatorIdem
from tadas.services.api.gateway.resolve import AdminService
from tadas.services.api.types.admin import (
    AddMemberRequest,
    CreateOrgRequest,
    OperatorView,
    PlatformSizeView,
)
from tadas.services.api.types.common import LIMIT_DEFAULT
from tadas.services.api.types.events import OperatorEventView
from tadas.services.api.types.tasks import TaskPageView
from tadas.services.api.types.tenancy import OrgView, UserPageView, UserView

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/me", response_model=OperatorView)
async def operator_me(admin: OperatorCtx, service: AdminService) -> OperatorView:
    """Who the plane admitted and what the entry grants; the check a skill
    makes before its first read."""
    return await service.me(admin)


@router.get("/size", response_model=PlatformSizeView)
async def platform_size(admin: OperatorCtx, service: AdminService) -> PlatformSizeView:
    return await service.size(admin)


@router.get("/orgs", response_model=list[OrgView])
async def list_orgs(
    admin: OperatorCtx, service: AdminService, limit: int = LIMIT_DEFAULT
) -> list[OrgView]:
    return await service.get_orgs(admin, limit)


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
