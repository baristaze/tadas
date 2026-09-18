"""Durable background work is a row: what to do, for which record, under
which producer key, on which lane, and its own claim. Payload shapes are
fixed per kind by `WORK_PAYLOADS`, as `TOPIC_PAYLOADS` fixes them per topic;
the row stores the dump."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import Field

from tadas.om.base import FrozenMapping, Identifiable, Platform, Trackable


class WorkKind(str, Enum):
    NOOP = "NOOP"  # the maintenance worker's kind: no work beyond the sweep


class WorkStatus(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    DONE = "done"
    FAILED = "failed"


class WorkItem(Identifiable, Trackable):
    kind: WorkKind  # what to do
    target_id: UUID  # the record it advances
    idempotency_key: UUID  # unique
    payload: FrozenMapping = Field(default_factory=dict)  # the dump of WORK_PAYLOADS[kind]
    lane: str = (
        "default"  # routing: "default", "region:<id>", ...; a string, because lanes are dynamic
    )
    status: WorkStatus = WorkStatus.QUEUED
    available_at: datetime  # not before
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    attempts: int = 0
    max_attempts: int = 3
    last_error: str | None = None


class NoopPayload(Platform):
    """The NOOP kind carries nothing."""


WORK_PAYLOADS: dict[WorkKind, type[Platform]] = {
    WorkKind.NOOP: NoopPayload,
}
"""The payload shape of every kind; enqueue validates the item's payload against it."""
