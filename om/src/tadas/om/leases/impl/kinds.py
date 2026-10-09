"""The hooks of the kinds the mechanism ships: the `noop` resource kind, and
the orchestration as a waiter. A product registers its own beside them in
the root."""

from uuid import UUID

from tadas.om.context import TenantContext
from tadas.om.exceptions import NotFound
from tadas.om.leases.hooks import ResourceKindInterface, WaiterInterface
from tadas.om.leases.types.lease import Lease
from tadas.om.leases.types.request import LeaseRequest
from tadas.om.leases.types.resource import Resource
from tadas.om.orchestrations import OrchestrationsManagerInterface
from tadas.om.orchestrations.rules import is_settled
from tadas.om.orchestrations.types.orchestration import ParkReason
from tadas.om.outbox.types.row import OutboxRow, outbox_row
from tadas.om.work.types.work_item import WakeParkedPayload, WorkKind, work_row_kind


class NoopResourceKindImpl(ResourceKindInterface):
    """A grant starts nothing, and every request may be granted."""

    async def may_grant(
        self, ctx: TenantContext, resource: Resource, request: LeaseRequest
    ) -> bool:
        return True

    def grant_rows(
        self, ctx: TenantContext, resource: Resource, request: LeaseRequest, lease: Lease
    ) -> tuple[OutboxRow, ...]:
        return ()


class OrchestrationWaiterImpl(WaiterInterface):
    """A long-running record waits on its request parked on `resource`. It
    waits while it has not settled. The grant wakes it, and so does its
    request's end without a lease; its next step asks again by its key and
    finds its lease, or the request's end, and fails or asks anew. A
    revocation tells it nothing: its next renewal is refused, and its step
    stops there."""

    def __init__(self, orchestrations: OrchestrationsManagerInterface) -> None:
        self._orchestrations = orchestrations

    async def still_waits(self, ctx: TenantContext, waiter_id: UUID) -> bool:
        try:
            record = await self._orchestrations.get(ctx, waiter_id)
        except NotFound:
            return False
        return not is_settled(record)

    def wake_rows(self, ctx: TenantContext, waiter_id: UUID, lease: Lease) -> tuple[OutboxRow, ...]:
        return self._wake(ctx, waiter_id)

    def end_rows(
        self, ctx: TenantContext, waiter_id: UUID, request: LeaseRequest
    ) -> tuple[OutboxRow, ...]:
        return self._wake(ctx, waiter_id)

    def revoke_rows(
        self, ctx: TenantContext, waiter_id: UUID, lease: Lease
    ) -> tuple[OutboxRow, ...]:
        return ()

    @staticmethod
    def _wake(ctx: TenantContext, waiter_id: UUID) -> tuple[OutboxRow, ...]:
        """A `WAKE_PARKED` item naming the one record."""
        payload = WakeParkedPayload(reason=ParkReason.RESOURCE, record_id=waiter_id)
        return (
            outbox_row(
                ctx,
                work_row_kind(WorkKind.WAKE_PARKED),
                ctx.org_id,
                payload.model_dump(mode="json"),
            ),
        )
