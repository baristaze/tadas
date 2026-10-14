"""The leases namespace's types: a leasable resource, its wait line, and its
leases."""

from tadas.client.schema.leases import (
    EndReason,
    LeasableResourceView,
    LeaseEntryView,
    LeasePageView,
    LeaseRequestView,
    LeaseStatus,
    LeaseView,
    PlaceView,
    RequestStatus,
    StandingView,
    WaitLineView,
)

__all__ = [
    "EndReason",
    "LeasableResourceView",
    "LeaseEntryView",
    "LeasePageView",
    "LeaseRequestView",
    "LeaseStatus",
    "LeaseView",
    "PlaceView",
    "RequestStatus",
    "StandingView",
    "WaitLineView",
]
