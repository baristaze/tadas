"""Operator routes under /v1/admin/*. They take OperatorContext and cannot
reach a tenant manager because no OpContext exists on this path."""

from uuid import UUID

from fastapi import APIRouter

from tadas.services.api.gateway.admin import OperatorCtx
from tadas.services.api.gateway.resolve import AdminService
from tadas.services.api.types.common import LIMIT_DEFAULT
from tadas.services.api.types.tenancy import OrgView

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/orgs", response_model=list[OrgView])
async def list_orgs(
    admin: OperatorCtx, service: AdminService, limit: int = LIMIT_DEFAULT
) -> list[OrgView]:
    return await service.get_orgs(admin, limit)


@router.delete("/orgs/{org_id}", response_model=OrgView)
async def delete_org(admin: OperatorCtx, service: AdminService, org_id: UUID) -> OrgView:
    return await service.delete_org(admin, org_id)
