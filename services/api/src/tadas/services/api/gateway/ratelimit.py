"""Per-route rate limits counted in the shared cache so every replica shares
one budget. The subject is the credential id on an authenticated route and
the client address on an unauthenticated one; never a digest of the bearer.
The limits fail open: they guard against runaway clients and are not a
security boundary."""

from datetime import timedelta
from typing import Any

from fastapi import Depends, Request

from tadas.infra.cache import CacheScope
from tadas.infra.observability import OUTCOMES
from tadas.om.base import EMPTY_UUID, Platform
from tadas.om.exceptions import PlatformException
from tadas.om.opcontext import CredentialScope, OpContext
from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.resolve import container_of


class RateLimited(PlatformException):
    http_status = 429
    code = "rate_limited"

    def __init__(self, retry_after: timedelta) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after = retry_after


class RateLimit(Platform):
    limit: int
    window: timedelta


class RateLimitOptions(Platform):
    """One budget per rate-limited route, built from settings at boot and held
    on the container; the dependency reads its route's budget from here."""

    login: RateLimit

    def of(self, route: str) -> RateLimit:
        budgets = {"login": self.login}
        return budgets[route]


def subject_of(request: Request, ctx: CredentialScope | None) -> str:
    """The credential id when a credential was presented, else the client address."""
    if ctx is not None:
        return f"cred:{ctx.credential_id}"
    client = request.client.host if request.client else "unknown"
    return f"addr:{client}"


async def count(request: Request, route: str, ctx: OpContext | None) -> None:
    """Reads the tenant for the budget's scope and hands the context on to
    `subject_of` for the credential; no named scope covers both, so it says
    the stage."""
    container = container_of(request)
    budget = container.rate_limits.of(route)
    cache = container.infra.get_cache(CacheScope.RATE_LIMIT)
    key = f"{route}:{subject_of(request, ctx)}"
    # A credential's budget counts under its tenant; only the address-keyed,
    # unauthenticated path counts under the system scope.
    scope = ctx.org_id if ctx is not None else EMPTY_UUID
    total, remaining = await cache.increment(scope, key, budget.window)
    if total > budget.limit:
        OUTCOMES.labels(subsystem="rate_limit", outcome="rejected").inc()
        raise RateLimited(remaining)
    OUTCOMES.labels(subsystem="rate_limit", outcome="allowed").inc()


def rate_limited(route: str, *, authenticated: bool = False) -> Any:
    """A route dependency: `dependencies=[rate_limited("login")]`. The budget
    named by `route` must exist on RateLimitOptions. An authenticated route
    counts per credential id, an unauthenticated one per client address."""

    async def by_credential(request: Request, ctx: Ctx) -> None:
        await count(request, route, ctx)

    async def by_address(request: Request) -> None:
        await count(request, route, None)

    return Depends(by_credential if authenticated else by_address)
