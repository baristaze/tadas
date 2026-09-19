from abc import ABC, abstractmethod

from tadas.om.opcontext import OpContext
from tadas.om.work.types.work_item import WorkItem


class WorkHandlerInterface(ABC):
    """The one handler interface for background work. Handlers are idempotent:
    at-least-once delivery may run the same item twice."""

    @abstractmethod
    async def handle(self, ctx: OpContext, item: WorkItem) -> None: ...
