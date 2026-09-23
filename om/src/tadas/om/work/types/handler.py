from abc import ABC, abstractmethod
from datetime import timedelta
from typing import ClassVar

from tadas.om.exceptions import WorkException
from tadas.om.opcontext import OpContext, Permission
from tadas.om.work.types.work_item import WorkItem


class WorkParked(WorkException):
    """A handler's guard: the work cannot run now, and nothing about it has
    failed. A dependency that asked to be left alone for a while (a rate
    limit with its Retry-After) is the case. The loop hands the item back
    for `resume_after` without spending an attempt, with the reason as its
    note. A guard parks; only a real bound fails."""

    code = "work_parked"

    def __init__(self, reason: str, resume_after: timedelta) -> None:
        super().__init__(reason)
        self.reason = reason
        self.resume_after = resume_after


class WorkHandlerInterface(ABC):
    """The one handler interface for background work. Handlers are idempotent:
    at-least-once delivery may run the same item twice. A handler returns
    when the work is done or has nothing left to do, raises `WorkParked`
    when it must wait, and raises anything else when it failed."""

    REQUIRES: ClassVar[tuple[Permission, ...]] = ()
    """The permissions the handler's calls take. Whoever may ask for the kind
    holds them all (`WORK_ENQUEUE_PERMISSIONS`), which a test holds."""

    @abstractmethod
    async def handle(self, ctx: OpContext, item: WorkItem) -> None: ...
