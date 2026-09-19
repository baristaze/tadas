"""One row per handoff: the record that changed, how, its snapshot, and the
principal and request that produced it, so the event the relay appends
carries the same provenance the core write did."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from tadas.om.base import Created, FrozenMapping, Identifiable, new_id, utcnow
from tadas.om.opcontext import ProvenanceScope


class OutboxRow(Identifiable, Created):
    kind: str  # "<namespace>.<entity>.<created|updated|deleted>"
    target_id: UUID  # the record that changed
    payload: FrozenMapping = Field(
        default_factory=dict, validate_default=True
    )  # the record's snapshot
    actor_id: UUID  # the user whose request produced it
    request_id: UUID  # the request that produced it
    app: str  # the AppType value the request came from
    done_at: datetime | None = None  # set by the relay; the sweep purges done rows


def outbox_row(
    ctx: ProvenanceScope, kind: str, target_id: UUID, payload: Mapping[str, Any]
) -> OutboxRow:
    """The row a manager writes beside its core row, under the caller's provenance:
    the actor, the request, and the app are all the row reads from the context."""
    return OutboxRow(
        id=new_id(),
        created_at=utcnow(),
        kind=kind,
        target_id=target_id,
        payload=payload,
        actor_id=ctx.user_id,
        request_id=ctx.request_id,
        app=ctx.app.type.value,
    )


def snapshot(entity: BaseModel, *, exclude: frozenset[str] = frozenset()) -> Mapping[str, Any]:
    """The JSON-mode dump of an entity, minus the fields named; the payload of
    a `<namespace>.<entity>.<action>` row is the entity's snapshot."""
    return entity.model_dump(mode="json", exclude=set(exclude))
