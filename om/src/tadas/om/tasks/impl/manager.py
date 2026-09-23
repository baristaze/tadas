import logging
from datetime import timedelta
from uuid import UUID

from tadas.infra.observability import OUTCOMES
from tadas.om.base import PROVENANCE_FIELDS, Platform, utcnow
from tadas.om.exceptions import NotFound, PreconditionFailed, TenantMismatch, ValidationFailed
from tadas.om.media import MediaManagerInterface
from tadas.om.media.types.file import File, FilePurpose
from tadas.om.media.types.page import FilePage
from tadas.om.opcontext import OpContext, Permission
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import OutboxRow, outbox_row
from tadas.om.tasks.manager import TasksManagerInterface
from tadas.om.tasks.rules import is_between, position_after, renumbered, top_position
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.page import TaskPage
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus
from tadas.om.tenancy import TenancyManagerInterface

log = logging.getLogger(__name__)

NEIGHBOURS = 1
"""How many open places a placement reads: the top one for a task placed on
top, the one after the anchor for a move. The rules decide from that place
alone (tasks.rules.top_position, position_after, is_between), so the read
stays one row however long the open list grows."""


class TasksOptions(Platform):
    max_limit: int = 200
    retention: timedelta = timedelta(days=30)  # a deleted task is purged after this


class TasksManagerImpl(TasksManagerInterface):
    def __init__(
        self,
        storage: TasksStorageInterface,
        tenancy: TenancyManagerInterface,
        media: MediaManagerInterface,
        relay: OutboxRelayInterface,
        options: TasksOptions,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._media = media
        self._relay = relay
        self._options = options

    async def get_open_tasks(
        self, ctx: OpContext, criterion: TaskFilter, after: OpenTaskCursor | None, limit: int
    ) -> TaskPage:
        ctx.require(Permission.READ)
        self._own(ctx, criterion)
        limit = self._clamp(limit)
        rows = await self._storage.read_open_tasks(ctx.org_id, criterion, after, limit + 1)
        return self._page(rows, limit)

    async def get_done_tasks(
        self, ctx: OpContext, criterion: TaskFilter, before: TaskCursor | None, limit: int
    ) -> TaskPage:
        ctx.require(Permission.READ)
        self._own(ctx, criterion)
        limit = self._clamp(limit)
        rows = await self._storage.read_done_tasks(ctx.org_id, criterion, before, limit + 1)
        return self._page(rows, limit)

    async def get_task(self, ctx: OpContext, task_id: UUID) -> Task:
        ctx.require(Permission.READ)
        task = await self._storage.read_task(ctx.org_id, task_id)
        if task is None or task.deleted_at is not None:
            raise NotFound(f"task {task_id} not found")
        return task

    async def create_task(self, ctx: OpContext, task: Task) -> Task:
        ctx.require(Permission.WRITE)
        await self._verify(ctx, task)
        # The platform stamps the provenance and the clock, as enqueue does:
        # a caller cannot backdate a task or create one already deleted.
        now = utcnow()
        created = task.model_copy(
            update={
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
                "deleted_at": None,
                "deleted_by": None,
                "status": TaskStatus.OPEN,
                "position": await self._top_position(ctx, exclude=task.id),
                "version": 1,
            }
        )
        rows = (outbox_row(ctx, "tasks.task.created", created.id, {}),)  # ids only
        if not await self._storage.create_task(ctx.org_id, created, rows):
            # Ids are minted above storage, so the only way to present one twice
            # is a retry, and a retry must not create twice: the insert reported
            # the id and nothing changed, so the row as stored is the answer.
            existing = await self._storage.read_task(ctx.org_id, created.id)
            if existing is None:
                # The id is held, and not in this tenant: refused, never a 500.
                raise TenantMismatch(f"task {created.id} is not in {ctx.org_id}")
            return existing
        for row in rows:  # a write that also starts work carries a second row here
            await self._relay.relay(ctx.org_id, row)
        return created

    async def update_task(self, ctx: OpContext, task: Task, expected_version: int) -> Task:
        ctx.require(Permission.WRITE)
        current = await self.get_task(ctx, task.id)  # existence and tenancy, or NotFound
        await self._verify(ctx, task, current)
        # The copy starts from the stored row: the caller's entity supplies the
        # fields a caller may change, and the provenance and the fields the
        # manager owns stay as stored. The version is the caller's expected
        # one plus one, and the write is conditioned on the caller's, never on
        # the one read above, which would always match: a snapshot that missed
        # a write is refused, not merged. The copy carries a dump, so it is
        # validated, never model_copy.
        caller_owned = {*PROVENANCE_FIELDS, *Task.MANAGER_OWNED_FIELDS}
        changes: dict[str, object] = {
            **task.model_dump(exclude=caller_owned),
            "updated_at": utcnow(),
            "updated_by": ctx.user_id,
            "version": expected_version + 1,
        }
        if current.status == TaskStatus.DONE and task.status == TaskStatus.OPEN:
            changes["position"] = await self._top_position(ctx, exclude=task.id)
        updated = Task.model_validate({**current.model_dump(), **changes})
        await self._write(ctx, updated, expected_version, "updated")
        return updated

    async def move_task(
        self, ctx: OpContext, task_id: UUID, after_id: UUID | None, expected_version: int
    ) -> Task:
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
            at = (anchor.position, anchor.id)
            # The one place that follows the anchor is all the rules read.
            places = await self._storage.read_open_places(
                ctx.org_id, exclude=task_id, after=at, limit=NEIGHBOURS
            )
            position = position_after(at, places)
            if not is_between(at, position, places):
                return await self._renumber(ctx, task, anchor, expected_version)
        moved = task.model_copy(
            update={
                "position": position,
                "updated_at": utcnow(),
                "updated_by": ctx.user_id,
                "version": expected_version + 1,
            }
        )
        await self._write(ctx, moved, expected_version, "updated")
        return moved

    async def delete_task(self, ctx: OpContext, task_id: UUID, expected_version: int) -> Task:
        ctx.require(Permission.WRITE)
        task = await self.get_task(ctx, task_id)
        now = utcnow()
        deleted = task.model_copy(
            update={
                "deleted_at": now,
                "deleted_by": ctx.user_id,
                "updated_at": now,
                "updated_by": ctx.user_id,
                "version": expected_version + 1,
            }
        )
        await self._write(ctx, deleted, expected_version, "deleted")
        await self._detach_all(ctx, task_id)
        return deleted

    async def attach_file(self, ctx: OpContext, task_id: UUID, file: File) -> File:
        ctx.require(Permission.WRITE)
        await self.get_task(ctx, task_id)  # a live task of this tenant, or NotFound
        attached = file.model_copy(
            update={"purpose": FilePurpose.TASK_ATTACHMENT, "subject_id": task_id}
        )
        return await self._media.create_file(ctx, attached)

    async def get_attachments(
        self, ctx: OpContext, task_id: UUID, after: UUID | None, limit: int
    ) -> FilePage:
        await self.get_task(ctx, task_id)
        return await self._media.get_files(ctx, FilePurpose.TASK_ATTACHMENT, task_id, after, limit)

    async def remove_attachment(self, ctx: OpContext, task_id: UUID, file_id: UUID) -> File:
        ctx.require(Permission.WRITE)
        await self.get_task(ctx, task_id)
        file = await self._media.get_file(ctx, file_id)
        if file.purpose is not FilePurpose.TASK_ATTACHMENT or file.subject_id != task_id:
            raise NotFound(f"file {file_id} is not attached to task {task_id}")
        return await self._media.delete_file(ctx, file_id)

    async def _detach_all(self, ctx: OpContext, task_id: UUID) -> None:
        """The attachments go after the task, in writes of their own: the task
        is another namespace's row, so no commit holds both. The task's delete
        has committed by now and is the answer; a failure here is logged and
        counted, never raised, and the files it left stay out of every list,
        since a deleted task lists nothing, while they still count toward the
        tenant's usage."""
        try:
            await self._media.delete_subject_files(ctx, FilePurpose.TASK_ATTACHMENT, task_id)
        except Exception:
            log.exception("the attachments of deleted task %s were left live", task_id)
            OUTCOMES.labels(subsystem="tasks", outcome="detach_failed").inc()

    async def purge_deleted(self, ctx: OpContext) -> int:
        ctx.require(Permission.WRITE)
        if await self._tenancy.tenant_expired(ctx):
            # The tenant itself is past the retention, so it keeps nothing but
            # its org row. An open or a done task carries no `deleted_at`, so
            # the purge below would leave every one of them behind forever.
            return await self._storage.purge_tenant(ctx.org_id)
        return await self._storage.purge_deleted(ctx.org_id, utcnow() - self._options.retention)

    def _clamp(self, limit: int) -> int:
        """The page size a caller gets, at most `max_limit`."""
        return max(1, min(limit, self._options.max_limit))

    @staticmethod
    def _page(rows: list[Task], limit: int) -> TaskPage:
        """The clamp is on the page; the lookahead is one row past it, which
        storage was asked for and the page never carries. So a list truncated
        by the clamp still says a page follows, and the last page says none."""
        return TaskPage(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    @staticmethod
    def _own(ctx: OpContext, criterion: TaskFilter) -> None:
        if criterion.user_id != ctx.user_id:
            raise ValidationFailed("a task list is scoped to the caller")

    async def _top_position(self, ctx: OpContext, exclude: UUID) -> float:
        # The top place is all the rule reads.
        top = await self._storage.read_open_places(
            ctx.org_id, exclude=exclude, after=None, limit=NEIGHBOURS
        )
        return top_position(top)

    async def _renumber(self, ctx: OpContext, task: Task, anchor: Task, version: int) -> Task:
        """The gap after the anchor has closed at float precision, so the open
        list is renumbered with the task in its place: one write, conditioned
        on every row's version, and one outbox row per task whose position
        changed, since a client sorts by what it hears."""
        ordered = [t for t in await self._every_open_task(ctx) if t.id != task.id]
        # The anchor was read before this list was; a concurrent delete or
        # "mark done" of it between the two reads leaves the move with nothing
        # to follow. That is the caller's snapshot gone stale, the same answer
        # every other refused write here gives, not a crash inside the renumber.
        at = next((index for index, t in enumerate(ordered) if t.id == anchor.id), None)
        if at is None:
            raise PreconditionFailed(f"task {anchor.id} left the open list while {task.id} moved")
        ordered.insert(at + 1, task.model_copy(update={"version": version}))
        now = utcnow()
        updates: list[tuple[Task, int, tuple[OutboxRow, ...]]] = []
        moved = task
        for current, position in zip(ordered, renumbered(len(ordered)), strict=True):
            if current.id != task.id and current.position == position:
                continue
            placed = current.model_copy(
                update={
                    "position": position,
                    "updated_at": now,
                    "updated_by": ctx.user_id,
                    "version": current.version + 1,
                }
            )
            rows = (outbox_row(ctx, "tasks.task.updated", placed.id, {}),)
            updates.append((placed, current.version, rows))
            if current.id == task.id:
                moved = placed
        await self._storage.update_tasks(ctx.org_id, updates)
        for _, _, rows in updates:
            for row in rows:
                await self._relay.relay(ctx.org_id, row)
        return moved

    async def _every_open_task(self, ctx: OpContext) -> list[Task]:
        """Every open task of the org, top first, a page at a time."""
        criterion = TaskFilter(scope=TaskScope.TEAM, user_id=ctx.user_id)
        tasks: list[Task] = []
        after: OpenTaskCursor | None = None
        while True:
            page = await self._storage.read_open_tasks(
                ctx.org_id, criterion, after, self._options.max_limit
            )
            tasks.extend(page)
            if len(page) < self._options.max_limit:
                return tasks
            after = OpenTaskCursor(position=page[-1].position, id=page[-1].id)

    async def _verify(self, ctx: OpContext, task: Task, current: Task | None = None) -> None:
        """What a caller may not write. The assignee is checked when the
        assignment changes, never over one already stored: a member removed
        from the org leaves their tasks assigned, and marking such a task done
        or editing its title is an update about something else, which the
        assignment must not refuse. Assigning or reassigning is checked, and
        clearing the assignee is always allowed."""
        if not task.title.strip():
            raise ValidationFailed("a task needs a title")
        assigned = task.assignee_id
        if assigned is not None and (current is None or assigned != current.assignee_id):
            try:
                await self._tenancy.get_user(ctx, assigned)
            except NotFound:
                raise ValidationFailed("the assignee is not a member of this org") from None

    async def _write(self, ctx: OpContext, task: Task, expected_version: int, action: str) -> None:
        """The core row and the rows that announce it land in one storage call,
        conditioned on the version the caller read; the relay then appends the
        event and pushes at once, and the sweep catches what a crash left
        behind. Every push is also a record, so a client that missed the push
        replays by seq. A row carries ids and never a field's value, so the
        relay and the stream hold nothing a person's erasure has to find; a
        client that hears of a change reads the task."""
        rows = (outbox_row(ctx, f"tasks.task.{action}", task.id, {}),)
        await self._storage.update_task(ctx.org_id, task, expected_version, rows)
        for row in rows:
            await self._relay.relay(ctx.org_id, row)
