from uuid import UUID

from tadas.infra.topics import EntityChangedPayload, Topics, TopicsInterface
from tadas.om.base import Platform, new_id, utcnow
from tadas.om.events import EventsManagerInterface
from tadas.om.exceptions import Conflict, NotFound, ValidationFailed
from tadas.om.opcontext import OpContext, Permission
from tadas.om.tasks.manager import TasksManagerInterface
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.task import Task


class TasksOptions(Platform):
    max_limit: int = 200


class TasksManagerImpl(TasksManagerInterface):
    def __init__(
        self,
        storage: TasksStorageInterface,
        events: EventsManagerInterface,
        topics: TopicsInterface,
        options: TasksOptions,
    ) -> None:
        self._storage = storage
        self._events = events
        self._topics = topics
        self._options = options

    async def get_tasks(self, ctx: OpContext, limit: int) -> list[Task]:
        ctx.require(Permission.READ)
        return await self._storage.read_tasks(ctx.org_id, self._clamp(limit))

    async def get_task(self, ctx: OpContext, task_id: UUID) -> Task:
        ctx.require(Permission.READ)
        task = await self._storage.read_task(ctx.org_id, task_id)
        if task is None or task.deleted_at is not None:
            raise NotFound(f"task {task_id} not found")
        return task

    async def create_task(self, ctx: OpContext, task: Task) -> Task:
        ctx.require(Permission.WRITE)
        self._verify(task)
        if await self._storage.read_task(ctx.org_id, task.id) is not None:
            raise Conflict(f"task {task.id} already exists")
        created = task.model_copy(update={"created_by": ctx.user_id})
        await self._storage.write_task(ctx.org_id, created)
        await self._changed(ctx, created.id, "created")
        return created

    async def update_task(self, ctx: OpContext, task: Task) -> Task:
        ctx.require(Permission.WRITE)
        await self.get_task(ctx, task.id)  # existence and tenancy, or NotFound
        self._verify(task)
        updated = task.model_copy(update={"updated_at": utcnow()})
        await self._storage.write_task(ctx.org_id, updated)
        await self._changed(ctx, updated.id, "updated")
        return updated

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
    def _verify(task: Task) -> None:
        if not task.title.strip():
            raise ValidationFailed("a task needs a title")
        if not task.status.strip():
            raise ValidationFailed("a task needs a status")

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
