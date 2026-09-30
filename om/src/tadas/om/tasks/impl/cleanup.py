import logging
from datetime import UTC, date, datetime, time

from tadas.om.base import derived_id, utcnow
from tadas.om.context import Permission, TenantContext
from tadas.om.exceptions import NotFound
from tadas.om.orchestrations import OrchestrationsManagerInterface
from tadas.om.orchestrations.rules import advanced
from tadas.om.orchestrations.steps import step_rows
from tadas.om.orchestrations.types.orchestration import (
    Orchestration,
    OrchestrationKind,
    Step,
    TaskCleanupInput,
)
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import outbox_row
from tadas.om.tasks.cleanup import TasksCleanupManagerInterface
from tadas.om.tasks.impl.manager import TasksOptions
from tadas.om.tasks.rules import CLEANUP_BATCH, archive_cutoff, cleanup_part, cleanup_period
from tadas.om.tasks.storage import TasksStorageInterface

log = logging.getLogger(__name__)


class TasksCleanupManagerImpl(TasksCleanupManagerInterface):
    def __init__(
        self,
        storage: TasksStorageInterface,
        relay: OutboxRelayInterface,
        options: TasksOptions,
        *,
        orchestrations: OrchestrationsManagerInterface,
    ) -> None:
        self._orchestrations = orchestrations
        self._storage = storage
        self._relay = relay
        self._options = options

    async def open_cleanup(self, ctx: TenantContext) -> Orchestration | None:
        ctx.require(Permission.WRITE)
        now = utcnow()
        before = archive_cutoff(now, self._options.archive_after)
        if not await self._storage.read_archivable(ctx.org_id, before, 1):
            return None
        period = cleanup_period(now)
        day = datetime.combine(date.fromisoformat(period), time(), tzinfo=UTC)
        record_id = derived_id(ctx.org_id, day, cleanup_part(period))
        try:
            return await self._orchestrations.get(ctx, record_id)
        except NotFound:
            pass
        record = Orchestration(
            id=record_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            kind=OrchestrationKind.TASK_CLEANUP,
            input=TaskCleanupInput(
                older_than_days=self._options.archive_after.days, before=before
            ).model_dump(mode="json"),
            period=period,
        )
        return await self._orchestrations.start(ctx, record)

    async def step_cleanup(self, ctx: TenantContext, record: Orchestration) -> Orchestration:
        ctx.require(Permission.WRITE)
        before = TaskCleanupInput.model_validate(dict(record.input)).before
        ids = await self._storage.read_archivable(ctx.org_id, before, CLEANUP_BATCH)
        now = utcnow()
        after = advanced(
            record,
            now,
            ctx.user_id,
            cursor=record.cursor + len(ids),
            total=None,
            finished=len(ids) < CLEANUP_BATCH,
        )
        candidates = [
            (task_id, (outbox_row(ctx, "tasks.task.archived", task_id, {}),)) for task_id in ids
        ]
        rows_after = step_rows(ctx, after)
        archived = await self._storage.update_archived_in_step(
            ctx.org_id,
            candidates,
            before,
            now,
            ctx.user_id,
            Step(record=after, expected_version=record.version),
            rows_after,
        )
        landed_rows = [
            row
            for (_, task_rows), landed in zip(candidates, archived, strict=True)
            if landed
            for row in task_rows
        ]
        await self._relay.relay_all(ctx.org_id, landed_rows)
        await self._relay.relay_all(ctx.org_id, rows_after)
        if any(archived):
            log.info("archived %d done tasks in org %s", sum(archived), ctx.org_id)
        return after.model_copy(update={"applied": record.applied + sum(archived)})
