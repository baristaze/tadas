from datetime import datetime
from uuid import UUID

from tadas.infra.topics import EntityChangedPayload, Topics, TopicsInterface
from tadas.om.base import Platform, new_id, utcnow
from tadas.om.events import EventsManagerInterface
from tadas.om.exceptions import Conflict, NotFound, ValidationFailed
from tadas.om.opcontext import OpContext, Permission
from tadas.om.tasks.manager import TasksManagerInterface
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus
from tadas.om.tenancy import TenancyManagerInterface


class TasksOptions(Platform):
    max_limit: int = 200


class TasksManagerImpl(TasksManagerInterface):
    def __init__(
        self,
        storage: TasksStorageInterface,
        tenancy: TenancyManagerInterface,
        events: EventsManagerInterface,
        topics: TopicsInterface,
        options: TasksOptions,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._events = events
        self._topics = topics
        self._options = options

    async def get_open_tasks(self, ctx: OpContext, scope: TaskScope, limit: int) -> list[Task]:
        ctx.require(Permission.READ)
        return await self._storage.read_open_tasks(
            ctx.org_id, self._for_user(ctx, scope), self._clamp(limit)
        )

    async def get_done_tasks(
        self,
        ctx: OpContext,
        scope: TaskScope,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Task]:
        ctx.require(Permission.READ)
        return await self._storage.read_done_tasks(
            ctx.org_id, self._for_user(ctx, scope), before, self._clamp(limit)
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
        if await self._storage.read_task(ctx.org_id, task.id) is not None:
            raise Conflict(f"task {task.id} already exists")
        created = task.model_copy(
            update={
                "created_by": ctx.user_id,
                "status": TaskStatus.OPEN,
                "position": await self._top_position(ctx, exclude=task.id),
            }
        )
        await self._storage.write_task(ctx.org_id, created)
        await self._changed(ctx, created.id, "created")
        return created

    async def update_task(self, ctx: OpContext, task: Task) -> Task:
        ctx.require(Permission.WRITE)
        current = await self.get_task(ctx, task.id)  # existence and tenancy, or NotFound
        await self._verify(ctx, task)
        update: dict[str, object] = {"updated_at": utcnow()}
        if current.status == TaskStatus.DONE and task.status == TaskStatus.OPEN:
            update["position"] = await self._top_position(ctx, exclude=task.id)
        updated = task.model_copy(update=update)
        await self._storage.write_task(ctx.org_id, updated)
        await self._changed(ctx, updated.id, "updated")
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
            following = [p for p in positions if p > anchor.position]
            position = (anchor.position + following[0]) / 2 if following else anchor.position + 1.0
        moved = task.model_copy(update={"position": position, "updated_at": utcnow()})
        await self._storage.write_task(ctx.org_id, moved)
        await self._changed(ctx, moved.id, "updated")
        return moved

    async def delete_task(self, ctx: OpContext, task_id: UUID) -> Task:
        ctx.require(Permission.WRITE)
        task = await self.get_task(ctx, task_id)
        now = utcnow()
        deleted = task.model_copy(
            update={"deleted_at": now, "deleted_by": ctx.user_id, "updated_at": now}
        )
        await self._storage.write_task(ctx.org_id, deleted)
        await self._changed(ctx, deleted.id, "deleted")
        return deleted

    def _clamp(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_limit))

    @staticmethod
    def _for_user(ctx: OpContext, scope: TaskScope) -> UUID | None:
        return ctx.user_id if scope == TaskScope.MINE else None

    async def _top_position(self, ctx: OpContext, exclude: UUID) -> float:
        positions = await self._storage.read_open_positions(ctx.org_id, exclude=exclude)
        return positions[0] - 1.0 if positions else 0.0

    async def _verify(self, ctx: OpContext, task: Task) -> None:
        if not task.title.strip():
            raise ValidationFailed("a task needs a title")
        if task.assignee_id is not None:
            try:
                await self._tenancy.get_user(ctx, task.assignee_id)
            except NotFound:
                raise ValidationFailed("the assignee is not a member of this org") from None

    async def _changed(self, ctx: OpContext, task_id: UUID, action: str) -> None:
        """The core row is written; now the stream row, then the push. Every push
        is also a record, so a client that missed the push replays by seq."""
        event = await self._events.record(ctx, "task", task_id, action, new_id())
        await self._topics.publish(
            Topics.ENTITY_CHANGED,
            EntityChangedPayload(
                idempotency_key=event.idempotency_key,
                produced_at=event.produced_at,
                org_id=ctx.org_id,
                entity=event.entity,
                entity_id=event.entity_id,
                action=event.action,
                seq=event.seq,
            ),
        )
