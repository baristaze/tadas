"""The operator service: takes OperatorContext and never an OpContext. A
read of one tenant names it by id; the views are the tenant's own."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.idempotency.types.attempt import Attempt
from tadas.om.opcontext import OperatorContext
from tadas.om.tasks.types.task import TaskStatus
from tadas.services.api.types.admin import (
    AddMemberRequest,
    CreateOrgRequest,
    OperatorView,
    PlatformSizeView,
)
from tadas.services.api.types.events import OperatorEventView
from tadas.services.api.types.tasks import TaskPageView
from tadas.services.api.types.tenancy import OrgView, UserPageView, UserView


class AdminServiceInterface(ABC):
    @abstractmethod
    async def get_orgs(self, admin: OperatorContext, limit: int) -> list[OrgView]: ...

    @abstractmethod
    async def me(self, admin: OperatorContext) -> OperatorView: ...

    @abstractmethod
    async def size(self, admin: OperatorContext) -> PlatformSizeView: ...

    @abstractmethod
    async def create_org(
        self, admin: OperatorContext, body: CreateOrgRequest, attempt: Attempt
    ) -> OrgView: ...

    @abstractmethod
    async def get_org(self, admin: OperatorContext, org_id: UUID) -> OrgView: ...

    @abstractmethod
    async def get_members(
        self, admin: OperatorContext, org_id: UUID, cursor: str | None, limit: int
    ) -> UserPageView: ...

    @abstractmethod
    async def add_member(
        self, admin: OperatorContext, org_id: UUID, body: AddMemberRequest, attempt: Attempt
    ) -> UserView: ...

    @abstractmethod
    async def get_tasks(
        self,
        admin: OperatorContext,
        org_id: UUID,
        status: TaskStatus,
        cursor: str | None,
        limit: int,
    ) -> TaskPageView: ...

    @abstractmethod
    async def get_events(
        self, admin: OperatorContext, org_id: UUID, after_seq: int, limit: int
    ) -> list[OperatorEventView]: ...

    @abstractmethod
    async def delete_org(self, admin: OperatorContext, org_id: UUID) -> OrgView: ...
