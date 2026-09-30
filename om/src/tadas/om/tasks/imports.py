"""The imports duty of the tasks manager: tasks made from the rows of a CSV
file, a long job kept as an orchestration."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.context import TenantContext
from tadas.om.media.types.file import File
from tadas.om.orchestrations.types.orchestration import Orchestration, OrchestrationPage


class TasksImportsManagerInterface(ABC):
    """A delegate of `TasksManagerInterface`, reached as `tasks.imports`.
    Every operation takes `TenantContext`."""

    @abstractmethod
    async def create_import_file(self, ctx: TenantContext, file: File) -> File:
        """Starts the upload of a CSV file to import: the media namespace
        lands it pending under the `task_import` purpose and its bounds,
        whatever purpose and subject the caller's file names. The bytes and
        the confirm go through the media namespace."""
        ...

    @abstractmethod
    async def start_import(
        self, ctx: TenantContext, import_id: UUID, file_id: UUID
    ) -> Orchestration:
        """Starts the import of a stored `task_import` file: the record and
        the work row of its first step, in one commit. The rows are read by
        the worker, a batch a step. An id written already answers the import
        as stored."""
        ...

    @abstractmethod
    async def get_import(self, ctx: TenantContext, import_id: UUID) -> Orchestration: ...

    @abstractmethod
    async def get_imports(self, ctx: TenantContext, limit: int) -> OrchestrationPage:
        """The org's newest imports, newest first."""
        ...

    @abstractmethod
    async def resume_import(self, ctx: TenantContext, import_id: UUID) -> Orchestration:
        """A person's wake of a parked import: it runs again from its cursor,
        and parks again at once if the plan still has no room."""
        ...

    @abstractmethod
    async def step_import(self, ctx: TenantContext, record: Orchestration) -> Orchestration:
        """One step of an import: reads the file, checks its bounds, and makes
        the tasks of the next batch of rows in one commit with the record's
        next cursor (`TasksStorageInterface.create_tasks_in_step`). A row that
        makes no task is skipped and named; a row that would take the org past
        its plan's bound of active tasks parks the record `plan_limit` at that
        row; a file past a bound fails it. Each task's id is derived from the
        import and the row, so a step run twice makes each task once."""
        ...
