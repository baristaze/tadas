"""The billing namespace's kinds of work, which the business root registers
in `KINDS` below its marker (`work.kinds`)."""

from enum import StrEnum

from tadas.om.billing.types.work import SyncSeatsPayload
from tadas.om.context import Permission
from tadas.om.work.kinds import WorkKindSpec


class BillingKind(StrEnum):
    """The names of the billing namespace's kinds of work."""

    SYNC_SEATS = "SYNC_SEATS"  # a per-seat plan's quantity follows the member count


BILLING_KINDS: tuple[WorkKindSpec, ...] = (
    WorkKindSpec(BillingKind.SYNC_SEATS, SyncSeatsPayload, Permission.MANAGE_MEMBERS),
)
"""The billing namespace's kinds, each on the default lane."""
