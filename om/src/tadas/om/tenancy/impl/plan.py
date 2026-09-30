"""What the org's plan asks of tenancy, where more than one duty asks it: a
seat for one more member, the row a per-seat plan's count follows, and
whether the plan has api keys. The manager and its delegates each reach
these, so each is written once, as `shared.py` holds the rest. `plans` is
what the levers ask: the org's plan is read from it."""

from tadas.om.billing.manager import EntitlementsInterface
from tadas.om.billing.rules import refuse_past, seats_metered
from tadas.om.billing.types.billing import Entitlements
from tadas.om.billing.types.plan import Lever
from tadas.om.context import TenantContext
from tadas.om.outbox.types.row import OutboxRow, outbox_row
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.work.types.work_item import WorkKind, work_row_kind


async def seat_rows(plans: EntitlementsInterface, ctx: TenantContext) -> tuple[OutboxRow, ...]:
    """The row that asks for a per-seat subscription's quantity to follow a
    change of members, when the org's plan is per seat; none otherwise.
    It rides the change's own commit, as work that follows a write does."""
    entitlements = await plans.get_entitlements(ctx)
    if not seats_metered(entitlements.plan):
        return ()
    return (outbox_row(ctx, work_row_kind(WorkKind.SYNC_SEATS), ctx.org_id, {}),)


async def refuse_past_seats(
    storage: TenancyStorageInterface, plans: EntitlementsInterface, ctx: TenantContext
) -> None:
    """The plan's bound on members, for one more."""
    entitlements = await plans.get_entitlements(ctx)
    refuse_past(entitlements.plan, Lever.MEMBERS, await storage.count_members(ctx.org_id))


def refuse_keyless(entitlements: Entitlements) -> None:
    """PlanLimitReached when the org's plan has no api keys. A key of such
    an org is kept and refused, never revoked: the refusal says why, and
    the key works again the day the org is on a plan with keys."""
    refuse_past(entitlements.plan, Lever.API_KEYS, 0)
