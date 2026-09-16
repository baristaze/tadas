"""Edge idempotency: a creating POST accepts an Idempotency-Key. The first
response is stored per tenant under the key and replayed on a retry."""

import json
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request, Response
from pydantic import BaseModel

from tadas.infra.cache import CacheInterface, CacheScope
from tadas.services.api.gateway.auth import Ctx

REPLAY_TTL = timedelta(hours=24)
REPLAYED_HEADER = "Idempotent-Replayed"


class Idempotency:
    def __init__(self, cache: CacheInterface, org_id: UUID, key: str | None) -> None:
        self._cache = cache
        self._org_id = org_id
        self._key = key

    async def replay(self) -> Response | None:
        """The stored response for this key, or None when the request is new."""
        if self._key is None:
            return None
        raw = await self._cache.get(self._org_id, f"idempotency:{self._key}")
        if raw is None:
            return None
        stored = json.loads(raw)
        return Response(
            content=stored["body"],
            status_code=stored["status"],
            media_type="application/json",
            headers={REPLAYED_HEADER: "true"},
        )

    async def store(self, view: BaseModel, status: int) -> Response:
        body = view.model_dump_json()
        if self._key is not None:
            await self._cache.put(
                self._org_id,
                f"idempotency:{self._key}",
                json.dumps({"status": status, "body": body}).encode(),
                REPLAY_TTL,
            )
        return Response(content=body, status_code=status, media_type="application/json")


async def idempotency(
    request: Request,
    ctx: Ctx,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Idempotency:
    cache = request.app.state.container.infra.get_cache(CacheScope.NETWORK_RESPONSE)
    return Idempotency(cache, ctx.org_id, idempotency_key)


Idem = Annotated[Idempotency, Depends(idempotency)]
