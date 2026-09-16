"""Durable background work is a row: what to do, for which record, under
which producer key, and its own claim."""

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import Field

from tadas.om.base import Identifiable, Trackable


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
    payload: Mapping[str, Any] = Field(default_factory=dict)
    queue: str = "default"  # routing: "default", "region:<id>", ...
    status: WorkStatus = WorkStatus.QUEUED
    available_at: datetime  # not before
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    attempts: int = 0
    max_attempts: int = 3
    last_error: str | None = None
