"""Every push is also a record. An event names the record that changed and
carries the tenant's sequence number, so a client that reconnects asks for
everything after the last one it saw."""

from datetime import datetime
from uuid import UUID

from tadas.om.base import Identifiable


class Event(Identifiable):
    seq: int = 0  # per tenant, monotonic; 0 until storage assigns it on append
    entity: str  # "task", "api_key", ...
    entity_id: UUID
    action: str  # created | updated | deleted
    produced_at: datetime
    idempotency_key: UUID  # the key the matching topic payload carries
    actor_id: UUID  # the user whose request produced it
    request_id: UUID  # the request that produced it, from the context
