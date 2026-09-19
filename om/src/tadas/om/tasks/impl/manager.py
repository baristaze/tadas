from datetime import timedelta
from uuid import UUID

from tadas.om.base import Platform, utcnow
from tadas.om.exceptions import NotFound, ValidationFailed
from tadas.om.opcontext import OpContext, Permission
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import outbox_row, snapshot
from tadas.om.tasks.manager import TasksManagerInterface
from tadas.om.tasks.rules import position_after, top_position
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.filter import TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskStatus
from tadas.om.tenancy import TenancyManagerInterface


class TasksOptions(Platform):
    max_limit: int = 200
    retention: timedelta = timedelta(days=30)  # a deleted task is purged after this


class TasksManagerImpl(TasksManagerInterface):
    def __init__(
        self,
        storage: TasksStorageInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: TasksOptions,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._relay = relay
        self._options = options

    async def get_open_tasks(self, ctx: OpContext, criterion: TaskFilter, limit: int) -> list[Task]:
        ctx.require(Permission.READ)
        self._own(ctx, criterion)
        return await self._storage.read_open_tasks(ctx.org_id, criterion, self._clamp(limit))

    async def get_done_tasks(
        self, ctx: OpContext, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> list[Task]:
        ctx.require(Permission.READ)
        self._own(ctx, criterion)
        return await self._storage.read_done_tasks(
            ctx.org_id, criterion, before, self._clamp(limit)
        )

    async def get_task(self, ctx: OpContext, task_id: UUID) -> Task:
        ctx.require(Permission.READ)
        task = await self._storage.read_task(ctx.org_id, task_id)
        if task is None or task.deleted_at is not None:
            raise NotFound(f"task {task_id} not found")
        return task

    async def create_task(self, ctx: OpContext, task: Task) -> Task:
        ctx.require(Permission.WRITE)
        await self._verify(ctx, task)
        created = task.model_copy(
            update={
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
                "status": TaskStatus.OPEN,
                "position": await self._top_position(ctx, exclude=task.id),
            }
        )
        row = outbox_row(ctx, "tasks.task.created", created.id, snapshot(created))
        if not await self._storage.create_task(ctx.org_id, created, row):
            # Ids are minted above storage, so the only way to present one twice
            # is a retry, and a retry must not create twice: the insert reported
            # the id and nothing changed, so the row as stored is the answer.
            existing = await self._storage.read_task(ctx.org_id, created.id)
            assert existing is not None
            return existing
        await self._relay.relay(ctx.org_id, row)
        return created

    async def update_task(self, ctx: OpContext, task: Task) -> Task:
        ctx.require(Permission.WRITE)
        current = await self.get_task(ctx, task.id)  # existence and tenancy, or NotFound
        await self._verify(ctx, task)
        update: dict[str, object] = {"updated_at": utcnow(), "updated_by": ctx.user_id}
        if current.status == TaskStatus.DONE and task.status == TaskStatus.OPEN:
            update["position"] = await self._top_position(ctx, exclude=task.id)
        updated = task.model_copy(update=update)
        await self._write(ctx, updated, "updated")
        return updated

    async def move_task(self, ctx: OpContext, task_id: UUID, after_id: UUID | None) -> Task:
        ctx.require(Permission.WRITE)
        task = await self.get_task(ctx, task_id)
        if task.status != TaskStatus.OPEN:
            raise ValidationFailed("only an open task can be moved")
        if after_id == task_id:
            raise ValidationFailed("a task cannot be placed after itself")
        if after_id is None:
            position = await self._top_position(ctx, exclude=task_id)
        else:
            anchor = await self.get_task(ctx, after_id)
            if anchor.status != TaskStatus.OPEN:
                raise ValidationFailed("a task can only be placed after an open task")
            positions = await self._storage.read_open_positions(ctx.org_id, exclude=task_id)
            position = position_after(anchor.position, positions)
        moved = task.model_copy(
            update={"position": position, "updated_at": utcnow(), "updated_by": ctx.user_id}
        )
        await self._write(ctx, moved, "updated")
        return moved

    async def delete_task(self, ctx: OpContext, task_id: UUID) -> Task:
        ctx.require(Permission.WRITE)
        task = await self.get_task(ctx, task_id)
        now = utcnow()
        deleted = task.model_copy(
            update={
                "deleted_at": now,
                "deleted_by": ctx.user_id,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        await self._write(ctx, deleted, "deleted")
        return deleted

    async def purge_deleted(self, ctx: OpContext) -> int:
        ctx.require(Permission.WRITE)
        return await self._storage.purge_deleted(ctx.org_id, utcnow() - self._options.retention)

    def _clamp(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_limit))

    @staticmethod
    def _own(ctx: OpContext, criterion: TaskFilter) -> None:
        if criterion.user_id != ctx.user_id:
            raise ValidationFailed("a task list is scoped to the caller")

    async def _top_position(self, ctx: OpContext, exclude: UUID) -> float:
        return top_position(await self._storage.read_open_positions(ctx.org_id, exclude=exclude))

    async def _verify(self, ctx: OpContext, task: Task) -> None:
        if not task.title.strip():
            raise ValidationFailed("a task needs a title")
        if task.assignee_id is not None:
            try:
                await self._tenancy.get_user(ctx, task.assignee_id)
            except NotFound:
                raise ValidationFailed("the assignee is not a member of this org") from None

    async def _write(self, ctx: OpContext, task: Task, action: str) -> None:
        """The core row and its outbox row land in one storage call; the relay
        then appends the event and pushes at once, and the sweep catches what a
        crash left behind. Every push is also a record, so a client that missed
        the push replays by seq."""
        row = outbox_row(ctx, f"tasks.task.{action}", task.id, snapshot(task))
        await self._storage.write_task(ctx.org_id, task, row)
        await self._relay.relay(ctx.org_id, row)
