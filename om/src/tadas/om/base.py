"""Root of the object model: the base class, the mixins, and the two helpers
every entity constructor needs."""

from datetime import UTC, datetime
from uuid import UUID

import uuid_utils
from pydantic import BaseModel, ConfigDict


def new_id() -> UUID:
    """A time-ordered UUID v7 as a standard-library UUID."""
    return UUID(bytes=uuid_utils.uuid7().bytes)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Platform(BaseModel):
    """Root of the object model. Holds no fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Identifiable(Platform):
    id: UUID  # uuid_v7, from new_id()


class Named(Platform):
    name: str


class Trackable(Platform):
    created_at: datetime
    updated_at: datetime
    created_by: UUID  # id of the user who created it


class SoftDeletable(Platform):
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None


EMPTY_UUID = UUID(int=0)
"""The reserved system scope, and the sentinel for a required reference that means none."""
