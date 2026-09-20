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


WORK_ROW_PREFIX = "work."
"""The kind of the outbox row that asks for a work item: `work.<kind>`. A write
that also starts work lands such a row beside the one that announces the entity
change, in the same statement, and the relay enqueues the item it names: the
queue is a database role of its own, so no statement reaches both."""


def work_row_kind(kind: WorkKind) -> str:
    """The outbox row kind that asks for work of this kind."""
    return WORK_ROW_PREFIX + kind.value


def asks_for_work(row_kind: str) -> bool:
    """Whether an outbox row asks for a work item rather than announcing a
    change; the row's kind is its destination."""
    return row_kind.startswith(WORK_ROW_PREFIX)


class WorkStatus(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    DONE = "done"
    FAILED = "failed"


class WorkItem(Identifiable, Trackable):
    kind: WorkKind  # what to do
    target_id: UUID  # the record it advances
    idempotency_key: UUID  # unique
    payload: FrozenMapping = Field(
        default_factory=dict, validate_default=True
    )  # the dump of WORK_PAYLOADS[kind]
    lane: str = (
        "default"  # routing: "default", "region:<id>", ...; a string, because lanes are dynamic
    )
    status: WorkStatus = WorkStatus.QUEUED
    available_at: datetime  # not before
    claimed_by: str | None = None
    # Minted by the claim and cleared by every hand-back: completion, release,
    # deferral, and renewal condition on it in the statement itself, so a
    # worker that holds one item twice across a requeue cannot settle the
    # first claim's copy over the second's.
    claim_token: UUID | None = None
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
