"""Helpers the worker tests share."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

from tadas.infra.impl.local import InfraLocalImpl
from tadas.om.base import new_id, utcnow
from tadas.om.opcontext import AppContext, AppType, OpContext, RequestContext
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.work.types.handler import WorkHandlerInterface
from tadas.om.work.types.work_item import WorkItem, WorkKind
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.handler import NoopHandlerImpl
from tadas.workers.maintenance.loop import LoopOptions


class RecordingHandler(WorkHandlerInterface):
    """The production handler with a record of what it handled, for the tests only:
    the production handler keeps nothing per item."""

    def __init__(self) -> None:
        self._inner = NoopHandlerImpl()
        self.handled: list[WorkItem] = []

    async def handle(self, ctx: OpContext, item: WorkItem) -> None:
        await self._inner.handle(ctx, item)
        self.handled.append(item)


def build_container(tmp_path: Path) -> WorkerContainer:
    return WorkerContainer.for_tests(StorageMemoryImpl(), InfraLocalImpl(tmp_path))


def request() -> RequestContext:
    """The request stage a test mints at its edge, one per call."""
    return RequestContext(
        request_id=new_id(), app=AppContext(type=AppType.PORTAL, version="portal@test")
    )


async def sign_in(container: WorkerContainer) -> OpContext:
    tenancy = container.managers.tenancy
    _, org = await tenancy.bootstrap(
        request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann"
    )
    login = await tenancy.login(request(), "ann@example.test", "pw-1234")
    identity = await tenancy.authenticate_login(request(), login.token)
    issued = await tenancy.exchange_login(identity, org.id)
    return await tenancy.authenticate(request(), issued.token)


def make_item(ctx: OpContext, *, target_id: UUID | None = None) -> WorkItem:
    now = utcnow()
    return WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        kind=WorkKind.NOOP,
        target_id=target_id or new_id(),
        idempotency_key=new_id(),
        available_at=now,
    )


def fast_options(**overrides: object) -> LoopOptions:
    base: dict[str, object] = {
        "worker_id": "maintenance-test",
        "capacity": 2,
        "lease": timedelta(seconds=0.6),
        "heartbeat_interval": timedelta(seconds=0.05),
        "heartbeat_failure_limit": 2,
        "sweep_interval": timedelta(seconds=0.1),
        "poll_interval": timedelta(seconds=0.05),
    }
    return LoopOptions.model_validate({**base, **overrides})
