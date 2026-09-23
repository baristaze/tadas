from abc import ABC, abstractmethod
from typing import ClassVar

from tadas.om.opcontext import OpContext, Permission
from tadas.om.work.types.work_item import WorkItem


class WorkHandlerInterface(ABC):
    """The one handler interface for background work. Handlers are idempotent:
    at-least-once delivery may run the same item twice."""

    REQUIRES: ClassVar[tuple[Permission, ...]] = ()
    """The permissions the handler's calls take. Whoever may ask for the kind
    holds them all (`WORK_ENQUEUE_PERMISSIONS`), which a test holds."""

    @abstractmethod
    async def handle(self, ctx: OpContext, item: WorkItem) -> None: ...
