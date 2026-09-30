from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from tadas.om.base import derived_id, utcnow
from tadas.om.billing.manager import EntitlementsInterface
from tadas.om.context import Permission, TenantContext
from tadas.om.exceptions import NotFound, ValidationFailed
from tadas.om.media import MediaManagerInterface
from tadas.om.media.rules import BOUNDS
from tadas.om.media.types.file import File, FilePurpose, FileStatus
from tadas.om.orchestrations import OrchestrationsManagerInterface
from tadas.om.orchestrations.rules import advanced
from tadas.om.orchestrations.steps import step_rows
from tadas.om.orchestrations.types.orchestration import (
    FailReason,
    Orchestration,
    OrchestrationKind,
    OrchestrationPage,
    ParkReason,
    RowError,
    Step,
    TaskImportInput,
)
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import OutboxRow, versioned_row
from tadas.om.tasks.impl.manager import TasksOptions
from tadas.om.tasks.impl.shared import reminder_rows, room_left
from tadas.om.tasks.imports import TasksImportsManagerInterface
from tadas.om.tasks.rules import (
    IMPORT_BATCH,
    ImportedTask,
    ImportFileRefused,
    import_refusal,
    import_row_part,
    imported,
    parse_import,
    spread,
)
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.task import Task
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.tenancy.rules import fold_email


class TasksImportsManagerImpl(TasksImportsManagerInterface):
    def __init__(
        self,
        storage: TasksStorageInterface,
        tenancy: TenancyManagerInterface,
        media: MediaManagerInterface,
        relay: OutboxRelayInterface,
        options: TasksOptions,
        *,
        entitlements: EntitlementsInterface,
        orchestrations: OrchestrationsManagerInterface,
    ) -> None:
        self._orchestrations = orchestrations
        self._storage = storage
        self._tenancy = tenancy
        self._media = media
        self._relay = relay
        self._options = options
        self._entitlements = entitlements

    async def create_import_file(self, ctx: TenantContext, file: File) -> File:
        ctx.require(Permission.WRITE)
        upload = file.model_copy(update={"purpose": FilePurpose.TASK_IMPORT, "subject_id": None})
        return await self._media.create_file(ctx, upload)

    async def start_import(
        self, ctx: TenantContext, import_id: UUID, file_id: UUID
    ) -> Orchestration:
        ctx.require(Permission.WRITE)
        file = await self._media.get_file(ctx, file_id)
        if file.purpose is not FilePurpose.TASK_IMPORT:
            raise ValidationFailed(f"file {file_id} was not uploaded to be imported")
        if file.status is not FileStatus.STORED:
            raise ValidationFailed(f"file {file_id} has not been uploaded")
        now = utcnow()
        record = Orchestration(
            id=import_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            kind=OrchestrationKind.TASK_IMPORT,
            input=TaskImportInput(file_id=file_id).model_dump(mode="json"),
        )
        return await self._orchestrations.start(ctx, record)

    async def get_import(self, ctx: TenantContext, import_id: UUID) -> Orchestration:
        record = await self._orchestrations.get(ctx, import_id)
        if record.kind is not OrchestrationKind.TASK_IMPORT:
            raise NotFound(f"import {import_id} not found")
        return record

    async def get_imports(self, ctx: TenantContext, limit: int) -> OrchestrationPage:
        return await self._orchestrations.get_recent(ctx, OrchestrationKind.TASK_IMPORT, limit)

    async def resume_import(self, ctx: TenantContext, import_id: UUID) -> Orchestration:
        await self.get_import(ctx, import_id)
        return await self._orchestrations.resume(ctx, import_id)

    async def step_import(self, ctx: TenantContext, record: Orchestration) -> Orchestration:
        ctx.require(Permission.WRITE)
        file_id = TaskImportInput.model_validate(dict(record.input)).file_id
        try:
            file = await self._media.get_file(ctx, file_id)
        except NotFound:
            return await self._orchestrations.fail(ctx, record, FailReason.FILE_GONE)
        if file.status is not FileStatus.STORED:
            return await self._orchestrations.fail(ctx, record, FailReason.FILE_GONE)
        data = await self._media.get_content(ctx, file_id)
        try:
            rows = parse_import(data, BOUNDS[FilePurpose.TASK_IMPORT].max_bytes)
        except ImportFileRefused as refused:
            return await self._orchestrations.fail(ctx, record, FailReason(refused.reason))
        batch = rows[record.cursor : record.cursor + IMPORT_BATCH]
        members = await self._members(ctx) if any(r.assignee_email for r in batch) else {}
        room = await room_left(self._storage, self._entitlements, ctx)
        made: list[ImportedTask] = []
        skipped: list[RowError] = []
        cursor = record.cursor
        park: ParkReason | None = None
        for row in batch:
            refusal = import_refusal(row, members)
            if refusal is not None:
                skipped.append(RowError(row=row.number, reason=refusal))
            elif room is not None and len(made) >= room:
                # The guard: this row would take the org past its plan. The
                # record parks with the cursor on it, keeping every task the
                # rows before it made.
                park = ParkReason.PLAN_LIMIT
                break
            else:
                made.append(imported(row, members))
            cursor += 1
        now = utcnow()
        after = advanced(
            record,
            now,
            ctx.user_id,
            cursor=cursor,
            total=len(rows),
            skipped=skipped,
            finished=cursor >= len(rows),
            park=park,
        )
        tasks = await self._imported_tasks(ctx, record, made, now)
        rows_after = step_rows(ctx, after)
        written = await self._storage.create_tasks_in_step(
            ctx.org_id, tasks, Step(record=after, expected_version=record.version), rows_after
        )
        # The step's tasks relay together: their events take one run of
        # numbers under one hold of the tenant's cursor, not one hold each.
        landed_rows = [
            row
            for (_, task_rows), landed in zip(tasks, written, strict=True)
            if landed
            for row in task_rows
        ]
        await self._relay.relay_all(ctx.org_id, landed_rows)
        await self._relay.relay_all(ctx.org_id, rows_after)
        return after.model_copy(update={"applied": record.applied + sum(written)})

    async def _imported_tasks(
        self, ctx: TenantContext, record: Orchestration, made: Sequence[ImportedTask], now: datetime
    ) -> list[tuple[Task, tuple[OutboxRow, ...]]]:
        """The tasks a step makes, with the rows that announce them and
        schedule their reminders. They go to the bottom of the open list, in
        the file's order: an import adds to the list and does not reorder
        what the team placed. A task's id is derived from the import and its
        row, so a step run twice presents the same ids, and it is the task
        of the person who started the import. An imported task
        posts nothing to Slack: a file of a thousand rows is not a thousand
        messages."""
        if not made:
            return []
        last = await self._storage.read_last_place(ctx.org_id)
        ranks = spread(last[0] if last is not None else None, None, len(made))
        tasks: list[tuple[Task, tuple[OutboxRow, ...]]] = []
        for rank, row in zip(ranks, made, strict=True):
            task = Task(
                id=derived_id(record.id, record.created_at, import_row_part(row.number)),
                created_at=now,
                updated_at=now,
                # The person who started the import, whoever runs the step.
                created_by=record.created_by,
                updated_by=record.created_by,
                title=row.title,
                notes=row.notes,
                assignee_id=row.assignee_id,
                due_on=row.due_on,
                rank=rank,
            )
            rows = (
                versioned_row(ctx, "tasks.task.created", task.id, task.version),
                *reminder_rows(ctx, task),
            )
            tasks.append((task, rows))
        return tasks

    async def _members(self, ctx: TenantContext) -> dict[str, UUID]:
        """The org's members by address, folded: whom a row may assign."""
        members: dict[str, UUID] = {}
        after: UUID | None = None
        while True:
            page = await self._tenancy.members.get_users(ctx, after, self._options.max_limit)
            for user in page.items:
                if user.deleted_at is None:
                    members[fold_email(user.email)] = user.id
            if not page.has_more or not page.items:
                return members
            after = page.items[-1].id
