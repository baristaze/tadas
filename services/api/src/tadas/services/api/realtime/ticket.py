"""A long-lived connection is opened with a single-use, short-lived ticket
minted by an authenticated request, never with a long-lived credential in a
URL. Redeeming the ticket re-checks the credential behind it."""

import json
import secrets
from datetime import timedelta
from uuid import UUID

from tadas.infra.cache import CacheInterface
from tadas.om.base import EMPTY_UUID
from tadas.om.exceptions import InvalidCredential
from tadas.om.opcontext import CredentialKind, OpContext
from tadas.om.tenancy.rules import hash_token

TICKET_PREFIX = "tkt_"


class TicketStore:
    def __init__(self, cache: CacheInterface, ttl: timedelta) -> None:
        self._cache = cache
        self._ttl = ttl

    async def mint(self, ctx: OpContext) -> str:
        ticket = TICKET_PREFIX + secrets.token_urlsafe(24)
        behind = {
            "org_id": str(ctx.org_id),
            "credential_kind": ctx.security.credential_kind.value,
            "credential_id": str(ctx.security.credential_id),
        }
        await self._cache.put(EMPTY_UUID, self._key(ticket), json.dumps(behind).encode(), self._ttl)
        return ticket

    async def redeem(self, ticket: str) -> tuple[UUID, CredentialKind, UUID]:
        """Single use: the entry is invalidated as it is read."""
        if not ticket.startswith(TICKET_PREFIX):
            raise InvalidCredential("expected a socket ticket")
        raw = await self._cache.get(EMPTY_UUID, self._key(ticket))
        if raw is None:
            raise InvalidCredential("unknown or expired socket ticket")
        await self._cache.invalidate(EMPTY_UUID, self._key(ticket))
        behind = json.loads(raw)
        return (
            UUID(behind["org_id"]),
            CredentialKind(behind["credential_kind"]),
            UUID(behind["credential_id"]),
        )

    @staticmethod
    def _key(ticket: str) -> str:
        return f"ticket:{hash_token(ticket)}"
