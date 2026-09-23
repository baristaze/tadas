from datetime import timedelta
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
    ConfirmTotpRequest,
    CreateOrgRequest,
    IssuedOperatorTokenView,
    IssuedTotpSecretView,
    MintOperatorTokenRequest,
    OperatorView,
    PlatformSizeView,
    TotpConfirmedView,
)
from tadas.services.api.types.common import clamp_limit
from tadas.services.api.types.events import OperatorEventView
from tadas.services.api.types.tasks import TaskPageView, TaskView
from tadas.services.api.types.tenancy import OrgPageView, OrgView, UserPageView, UserView


class AdminServiceImpl(AdminServiceInterface):
    """The cursors an operator's read of a tenant hands out are the ones the
    tenant's own lists mint, so a page of a tenant's members or tasks is read
    the same way from either plane."""

    def __init__(self, tenancy: TenancyOperatorManagerInterface) -> None:
        self._tenancy = tenancy

    async def get_orgs(self, admin: OperatorContext, cursor: str | None, limit: int) -> OrgPageView:
        limit = clamp_limit(limit)
        after = decode_cursor("orgs", cursor) if cursor else None
        page = await self._tenancy.get_orgs(admin, after, limit)
        return OrgPageView(
            items=[OrgView.model_validate(o) for o in page.items],
            next_cursor=encode_cursor("orgs", page.items[-1].id) if page.has_more else None,
        )

    async def me(self, admin: OperatorContext) -> OperatorView:
        role = OperatorRole.WRITE if admin.has(OperatorPermission.WRITE) else OperatorRole.READ
        return OperatorView(identity_id=admin.identity_id, email=admin.email, operator_role=role)

    async def enrol_totp(self, admin: OperatorContext) -> IssuedTotpSecretView:
        issued = await self._tenancy.enrol_totp(admin)
        return IssuedTotpSecretView(otpauth_uri=issued.otpauth_uri)

    async def confirm_totp(
        self, admin: OperatorContext, body: ConfirmTotpRequest
    ) -> TotpConfirmedView:
        identity = await self._tenancy.confirm_totp(admin, body.totp_code)
        assert identity.totp_confirmed_at is not None, "a confirmed secret has its instant"
        return TotpConfirmedView(identity_id=identity.id, confirmed_at=identity.totp_confirmed_at)

    async def mint_token(
        self, admin: OperatorContext, body: MintOperatorTokenRequest
    ) -> IssuedOperatorTokenView:
        expires_in = None if body.expires_in is None else timedelta(seconds=body.expires_in)
        issued = await self._tenancy.issue_operator_token(admin, body.permission, expires_in)
        return IssuedOperatorTokenView(
            token=issued.token, expires_at=issued.expires_at, permission=issued.operator_role
        )

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
            admin, org_id, body.email, body.display_name, body.role, attempt
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
