from uuid import UUID

from tadas.om.opcontext import AdminContext
from tadas.om.tenancy import TenancyOperatorManagerInterface
from tadas.services.api.services.admin import AdminServiceInterface
from tadas.services.api.types.common import clamp_limit
from tadas.services.api.types.tenancy import OrgView


class AdminServiceImpl(AdminServiceInterface):
    def __init__(self, tenancy: TenancyOperatorManagerInterface) -> None:
        self._tenancy = tenancy

    async def get_orgs(self, admin: AdminContext, limit: int) -> list[OrgView]:
        orgs = await self._tenancy.get_orgs(admin, clamp_limit(limit))
        return [OrgView.model_validate(o) for o in orgs]

    async def delete_org(self, admin: AdminContext, org_id: UUID) -> OrgView:
        return OrgView.model_validate(await self._tenancy.delete_org(admin, org_id))
