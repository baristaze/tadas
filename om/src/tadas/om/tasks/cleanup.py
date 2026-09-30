"""The cleanup duty of the tasks manager: the daily archive of old done
tasks."""

from abc import ABC, abstractmethod

from tadas.om.context import TenantContext
from tadas.om.orchestrations.types.orchestration import Orchestration


class TasksCleanupManagerInterface(ABC):
    """A delegate of `TasksManagerInterface`, reached as `tasks.cleanup`.
    Every operation takes `TenantContext`."""

    @abstractmethod
    async def open_cleanup(self, ctx: TenantContext) -> Orchestration | None:
        """The sweep, for one tenant: opens today's cleanup record when the org
        has a done task unchanged since the day began, less the archive age
        (`tasks.rules.archive_cutoff`), and today's record is not open yet;
        the org, the kind, and the day are its unique key, so every sweep
        after the first one of the day opens nothing. None when there is
        nothing to archive."""
        ...

    @abstractmethod
    async def step_cleanup(self, ctx: TenantContext, record: Orchestration) -> Orchestration:
        """One step of a cleanup: archives the next batch of done tasks
        unchanged since the record's cutoff, in one conditional write with the
        record's next cursor (`TasksStorageInterface.update_archived_in_step`).
        A task reopened, edited, or deleted meanwhile is left alone."""
        ...
