from uuid import UUID

from tadas.om.idempotency.types.attempt import Attempt
from tadas.om.opcontext import OperatorContext, OperatorPermission, OperatorRole
from tadas.om.tasks.types.task import TaskStatus
from tadas.om.tenancy import TenancyOperatorManagerInterface
from tadas.services.api.services.admin import AdminServiceInterface
from tadas.services.api.services.impl.tasks import decode_cursor as decode_task_cursor
from tadas.services.api.services.impl.tasks import encode_cursor as encode_task_cursor
from tadas.services.api.services.impl.tenancy import decode_cursor, encode_cursor
from tadas.services.api.types.admin import (
    AddMemberRequest,
    CreateOrgRequest,
    OperatorView,
    PlatformSizeView,
)
from tadas.services.api.types.common import clamp_limit
from tadas.services.api.types.events import OperatorEventView
from tadas.services.api.types.tasks import TaskPageView, TaskView
from tadas.services.api.types.tenancy import OrgView, UserPageView, UserView


class AdminServiceImpl(AdminServiceInterface):
    """The cursors an operator's read of a tenant hands out are the ones the
    tenant's own lists mint, so a page of a tenant's members or tasks is read
    the same way from either plane."""

    def __init__(self, tenancy: TenancyOperatorManagerInterface) -> None:
        self._tenancy = tenancy

    async def get_orgs(self, admin: OperatorContext, limit: int) -> list[OrgView]:
        orgs = await self._tenancy.get_orgs(admin, clamp_limit(limit))
        return [OrgView.model_validate(o) for o in orgs]

    async def me(self, admin: OperatorContext) -> OperatorView:
        role = OperatorRole.WRITE if admin.has(OperatorPermission.WRITE) else OperatorRole.READ
        return OperatorView(identity_id=admin.identity_id, email=admin.email, operator_role=role)

    async def size(self, admin: OperatorContext) -> PlatformSizeView:
        return PlatformSizeView.model_validate(await self._tenancy.size(admin))

    async def create_org(
        self, admin: OperatorContext, body: CreateOrgRequest, attempt: Attempt
    ) -> OrgView:
        org = await self._tenancy.create_org(
            admin,
            body.name,
            body.slug,
            body.owner_email,
            body.owner_password,
            body.owner_name,
            attempt,
        )
        return OrgView.model_validate(org)

    async def get_org(self, admin: OperatorContext, org_id: UUID) -> OrgView:
        return OrgView.model_validate(await self._tenancy.get_org(admin, org_id))

    async def get_members(
        self, admin: OperatorContext, org_id: UUID, cursor: str | None, limit: int
    ) -> UserPageView:
        limit = clamp_limit(limit)
        after = decode_cursor("users", cursor) if cursor else None
        page = await self._tenancy.get_members(admin, org_id, after, limit)
        return UserPageView(
            items=[UserView.model_validate(u) for u in page.items],
            next_cursor=encode_cursor("users", page.items[-1].id) if page.has_more else None,
        )

    async def add_member(
        self, admin: OperatorContext, org_id: UUID, body: AddMemberRequest, attempt: Attempt
    ) -> UserView:
        user = await self._tenancy.add_member(
            admin, org_id, body.email, body.password, body.display_name, body.role, attempt
        )
        return UserView.model_validate(user)

    async def get_tasks(
        self,
        admin: OperatorContext,
        org_id: UUID,
        status: TaskStatus,
        cursor: str | None,
        limit: int,
    ) -> TaskPageView:
        limit = clamp_limit(limit)
        mark = decode_task_cursor(status, cursor) if cursor else None
        page = await self._tenancy.get_tasks(admin, org_id, status, mark, limit)
        return TaskPageView(
            items=[TaskView.model_validate(t) for t in page.items],
            next_cursor=encode_task_cursor(status, page.items[-1]) if page.has_more else None,
        )

    async def get_events(
        self, admin: OperatorContext, org_id: UUID, after_seq: int, limit: int
    ) -> list[OperatorEventView]:
        events = await self._tenancy.get_events(admin, org_id, after_seq, clamp_limit(limit))
        return [OperatorEventView.model_validate(e) for e in events]

    async def delete_org(self, admin: OperatorContext, org_id: UUID) -> OrgView:
        return OrgView.model_validate(await self._tenancy.delete_org(admin, org_id))
