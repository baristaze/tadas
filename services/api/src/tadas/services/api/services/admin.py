"""The operator service: takes AdminContext and never an OpContext."""

from uuid import UUID

from tadas.om.opcontext import AdminContext
from tadas.services.api.types.tenancy import OrgView


class AdminServiceInterface:
    async def get_orgs(self, admin: AdminContext, limit: int) -> list[OrgView]: ...

    async def delete_org(self, admin: AdminContext, org_id: UUID) -> OrgView: ...
