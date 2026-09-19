"""The operator service: takes OperatorContext and never an OpContext."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.opcontext import OperatorContext
from tadas.services.api.types.tenancy import OrgView


class AdminServiceInterface(ABC):
    @abstractmethod
    async def get_orgs(self, admin: OperatorContext, limit: int) -> list[OrgView]: ...

    @abstractmethod
    async def delete_org(self, admin: OperatorContext, org_id: UUID) -> OrgView: ...
