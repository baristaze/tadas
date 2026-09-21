import logging
from datetime import timedelta
from uuid import UUID

from tadas.infra.observability import current_traceparent
from tadas.om.base import EMPTY_UUID, Platform, new_id, utcnow
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event
from tadas.om.exceptions import NotFound, ValidationFailed
from tadas.om.idempotency.types.attempt import Attempt
from tadas.om.opcontext import OperatorContext, OperatorPermission, Role
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import OutboxRow, snapshot
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.page import TaskPage
from tadas.om.tasks.types.task import TaskScope, TaskStatus
from tadas.om.tenancy.impl.creates import (
    MAX_ORGS_PER_IDENTITY,
    add_member_to,
    create_org_with_owner,
)
from tadas.om.tenancy.operator import TenancyOperatorManagerInterface
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.page import OrgPage, UserPage
from tadas.om.tenancy.types.size import PlatformSize
from tadas.om.tenancy.types.user import User

log = logging.getLogger(__name__)

SIZE_WINDOW = timedelta(hours=24)
"""How far back the traffic figures of the platform's size look."""


class TenancyOperatorOptions(Platform):
    max_limit: int = 200
    max_orgs_per_identity: int = MAX_ORGS_PER_IDENTITY
    """The tenant manager's bound, held the same on this plane."""


class TenancyOperatorManagerImpl(TenancyOperatorManagerInterface):
    """Reads a tenant's rows through the storage of the namespace that owns
    them, under the tenant the operator named, never through that namespace's
    manager: a tenant manager takes an `OpContext`, and none exists on this
    plane."""

    def __init__(
        self,
        storage: TenancyStorageInterface,
        tasks: TasksStorageInterface,
        events: EventStorageInterface,
        relay: OutboxRelayInterface,
        options: TenancyOperatorOptions,
    ) -> None:
        self._storage = storage
        self._tasks = tasks
        self._events = events
        self._relay = relay
        self._options = options

    # Across every tenant.

    async def get_orgs(self, admin: OperatorContext, after: UUID | None, limit: int) -> OrgPage:
        admin.require(OperatorPermission.READ)
        limit = self._clamp(limit)
        rows = await self._storage.read_orgs(limit + 1, after)
        return OrgPage(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    async def size(self, admin: OperatorContext) -> PlatformSize:
        admin.require(OperatorPermission.READ)
        since = utcnow() - SIZE_WINDOW
        return PlatformSize(
            tenants=await self._storage.count_orgs(),
            users=await self._storage.count_users(),
            tasks_last_24h=await self._tasks.count_created_since(since),
            events_last_24h=await self._events.count_since(since),
            since=since,
        )

    async def create_org(
        self,
        admin: OperatorContext,
        name: str,
        slug: str,
        owner_email: str,
        owner_password: str,
        owner_name: str,
        attempt: Attempt | None = None,
    ) -> Org:
        admin.require(OperatorPermission.WRITE)
        org_id = new_id() if attempt is None else attempt.target_id
        if attempt is not None:
            # The rerun of a create that landed: the row as stored, in order.
            stored = await self._storage.read_org(org_id)
            if stored is not None:
                return stored
        org, _, _ = await create_org_with_owner(
            self._storage,
            org_id=org_id,
            org_name=name,
            slug=slug,
            email=owner_email,
            password=owner_password,
            display_name=owner_name,
            max_orgs=self._options.max_orgs_per_identity,
        )
        log.info("operator %s created org %s", admin.identity_id, org.id)
        return org

    # One named tenant.

    async def get_org(self, admin: OperatorContext, org_id: UUID) -> Org:
        admin.require(OperatorPermission.READ)
        org = await self._org(org_id)
        self._trail(admin, org_id, "org")
        return org

    async def get_members(
        self, admin: OperatorContext, org_id: UUID, after: UUID | None, limit: int
    ) -> UserPage:
        admin.require(OperatorPermission.READ)
        await self._org(org_id)
        limit = self._clamp(limit)
        rows = await self._storage.read_users(org_id, after, limit + 1)
        self._trail(admin, org_id, "members")
        return UserPage(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    async def add_member(
        self,
        admin: OperatorContext,
        org_id: UUID,
        email: str,
        password: str,
        display_name: str,
        role: Role,
        attempt: Attempt | None = None,
    ) -> User:
        admin.require(OperatorPermission.WRITE)
        org = await self._org(org_id)
        if org.deleted_at is not None:
            raise NotFound(f"org {org_id} not found")
        if role in (Role.OWNER, Role.SERVICE):
            raise ValidationFailed(f"{role.value} is not a role a member is added with")
        user_id = new_id() if attempt is None else attempt.target_id
        if attempt is not None:
            stored = await self._storage.read_user(org_id, user_id)
            if stored is not None:
                return stored
        user, created = await add_member_to(
            self._storage,
            self._relay,
            org_id=org_id,
            user_id=user_id,
            email=email,
            password=password,
            display_name=display_name,
            role=role,
            actor_id=admin.identity_id,
            request=admin,
            max_orgs=self._options.max_orgs_per_identity,
        )
        if created:
            log.info("operator %s added user %s to org %s", admin.identity_id, user.id, org_id)
        return user

    async def get_tasks(
        self,
        admin: OperatorContext,
        org_id: UUID,
        status: TaskStatus,
        cursor: OpenTaskCursor | TaskCursor | None,
        limit: int,
    ) -> TaskPage:
        admin.require(OperatorPermission.READ)
        await self._org(org_id)
        limit = self._clamp(limit)
        # Every task of the team: the filter's user is nobody, since `mine` is
        # about a member and an operator is not one.
        criterion = TaskFilter(scope=TaskScope.TEAM, user_id=EMPTY_UUID)
        if status is TaskStatus.OPEN:
            if cursor is not None and not isinstance(cursor, OpenTaskCursor):
                raise ValidationFailed("the cursor is not one the open list issued")
            rows = await self._tasks.read_open_tasks(org_id, criterion, cursor, limit + 1)
        else:
            if cursor is not None and not isinstance(cursor, TaskCursor):
                raise ValidationFailed("the cursor is not one the done list issued")
            rows = await self._tasks.read_done_tasks(org_id, criterion, cursor, limit + 1)
        self._trail(admin, org_id, "tasks")
        return TaskPage(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    async def get_events(
        self, admin: OperatorContext, org_id: UUID, after_seq: int, limit: int
    ) -> list[Event]:
        admin.require(OperatorPermission.READ)
        await self._org(org_id)
        events = await self._events.read_after(org_id, max(0, after_seq), self._clamp(limit))
        self._trail(admin, org_id, "events")
        return events

    async def delete_org(self, admin: OperatorContext, org_id: UUID) -> Org:
        admin.require(OperatorPermission.WRITE)
        org = await self._storage.read_org(org_id)
        if org is None or org.deleted_at is not None:
            raise NotFound(f"org {org_id} not found")
        now = utcnow()
        deleted = org.model_copy(
            update={
                "deleted_at": now,
                "deleted_by": admin.identity_id,
                "updated_at": now,
                "updated_by": admin.identity_id,
            }
        )
        # Announced like any change, into the tenant's own stream: the sockets
        # of the tenant, in whichever process holds them, close on the row the
        # relay publishes. An operator has no user in the tenant, so the actor
        # the row records is the operator's identity.
        row = OutboxRow(
            id=new_id(),
            created_at=now,
            org_id=org_id,
            kind="tenancy.org.deleted",
            target_id=org_id,
            payload=snapshot(deleted),
            actor_id=admin.identity_id,
            request_id=admin.request_id,
            app=admin.app.type.value,
            traceparent=current_traceparent(),
        )
        await self._storage.write_org(org_id, deleted, (row,))
        await self._relay.relay(org_id, row)
        log.info("operator %s deleted org %s", admin.identity_id, org_id)
        return deleted

    async def _org(self, org_id: UUID) -> Org:
        """The org named, deleted or not: an operator reads a deleted tenant's
        rows until the sweep takes them."""
        org = await self._storage.read_org(org_id)
        if org is None:
            raise NotFound(f"org {org_id} not found")
        return org

    def _clamp(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_limit))

    @staticmethod
    def _trail(admin: OperatorContext, org_id: UUID, what: str) -> None:
        """The support trail: one line per read of a tenant's rows, naming the
        tenant and the operator and nothing of what was read."""
        log.info("operator %s read %s of org %s", admin.identity_id, what, org_id)
