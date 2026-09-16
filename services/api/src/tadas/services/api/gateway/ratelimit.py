"""Per-route rate limits counted in the shared cache so every replica shares
one budget. The subject is the credential (by digest) or the client address.
The limits fail open: they guard against runaway clients and are not a
security boundary."""

import hashlib
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, Header, Request

from tadas.infra.cache import CacheScope
from tadas.infra.observability import OUTCOMES
from tadas.om.base import EMPTY_UUID, Platform
from tadas.om.exceptions import PlatformException
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


def subject_of(request: Request, authorization: str | None) -> str:
    if authorization:
        return "cred:" + hashlib.sha256(authorization.encode()).hexdigest()[:32]
    client = request.client.host if request.client else "unknown"
    return f"addr:{client}"


def rate_limited(route: str) -> Any:
    """A route dependency: `dependencies=[rate_limited("login")]`. The budget
    named by `route` must exist on RateLimitOptions."""

    async def dependency(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        container = container_of(request)
        budget = container.rate_limits.of(route)
        cache = container.infra.get_cache(CacheScope.RATE_LIMIT)
        key = f"{route}:{subject_of(request, authorization)}"
        count, remaining = await cache.increment(EMPTY_UUID, key, budget.window)
        if count > budget.limit:
            OUTCOMES.labels(subsystem="rate_limit", outcome="rejected").inc()
            raise RateLimited(remaining)
        OUTCOMES.labels(subsystem="rate_limit", outcome="allowed").inc()

    return Depends(dependency)
