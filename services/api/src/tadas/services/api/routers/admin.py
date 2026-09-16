"""Operator routes under /v1/admin/*. They take AdminContext and cannot
reach a tenant manager because no OpContext exists on this path."""

from fastapi import APIRouter, Request

from tadas.services.api.gateway.admin import AdminCtx
from tadas.services.api.types.common import LIMIT_DEFAULT, clamp_limit
from tadas.services.api.types.tenancy import OrgView

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/orgs", response_model=list[OrgView])
async def list_orgs(request: Request, admin: AdminCtx, limit: int = LIMIT_DEFAULT) -> list[OrgView]:
    orgs = await request.app.state.container.managers.tenancy.get_orgs(admin, clamp_limit(limit))
    return [OrgView.model_validate(o) for o in orgs]
