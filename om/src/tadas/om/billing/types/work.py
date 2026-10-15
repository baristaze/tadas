"""The payload of the billing namespace's kind of work (`billing.kinds`)."""

from tadas.om.base import OmBase


class SyncSeatsPayload(OmBase):
    """The item's target is the org; the count is read when the item runs,
    never when it was asked for, so items that run late or twice converge
    on the members the org has then."""
