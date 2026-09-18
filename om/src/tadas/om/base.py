"""Root of the object model: the base class, the mixins, and the two helpers
every entity constructor needs."""

from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Annotated, Any
from uuid import UUID

import uuid_utils
from pydantic import AfterValidator, BaseModel, ConfigDict, PlainSerializer


def new_id() -> UUID:
    """A time-ordered UUID v7 as a standard-library UUID."""
    return UUID(bytes=uuid_utils.uuid7().bytes)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Platform(BaseModel):
    """Root of the object model. Holds no fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


FrozenMapping = Annotated[
    Mapping[str, Any], AfterValidator(MappingProxyType), PlainSerializer(dict, return_type=dict)
]
"""A mapping field that stays frozen past the model: pydantic validates a
`Mapping` into a dict, so a read-only view is put around it, and the freeze
is deep as the guideline requires; a dump hands out a plain dict again."""


class Identifiable(Platform):
    id: UUID  # uuid_v7, from new_id()


class Named(Platform):
    name: str


class Created(Platform):
    """When a row came to be. For a record that is written once and never
    edited (an idempotency record, a socket ticket); an entity that changes
    composes `Trackable` instead."""

    created_at: datetime


class Trackable(Created):
    updated_at: datetime
    created_by: UUID  # id of the user who created it
    updated_by: UUID  # id of the user who last changed it


class SoftDeletable(Platform):
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None


EMPTY_UUID = UUID(int=0)
"""The platform, not a tenant or a person: the reserved system scope, and the
value of a required reference that no tenant and no person owns. It equals
infra's `SYSTEM_SCOPE` by value, so infra never imports it. A reference that
is genuinely optional is `None`, never `EMPTY_UUID`."""
