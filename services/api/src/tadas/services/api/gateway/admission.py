"""Admission: the bound on what this process has in flight, and the refusal
past it. It is not the rate limit beside it, and the two fail in opposite
directions. A rate limit is fairness between subjects, counted in the shared
cache, and fails open. Admission is this process defending itself, counted
here in its own memory, and fails closed: past the bound a request is refused
at once, so a saturated process answers and says why instead of queueing work
it cannot start and dying with every caller still waiting."""

from datetime import timedelta

from tadas.infra.observability import OUTCOMES
from tadas.om.exceptions import Unavailable
from tadas.services.api.gateway.envelope import error_response
from tadas.services.api.gateway.observability import (
    ASGIApp,
    Receive,
    Scope,
    Send,
    request_id_of,
)

UNBOUNDED_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})
"""The three operational routes `app.py` declares outside the versioned API,
which admission never refuses: a saturated process must still be able to say
that it is saturated, and the collector must still be able to read the
counter that says by how much. None of them does tenant work, liveness does
no I/O at all, and readiness carries a deadline of its own. The paths are
matched as they arrive, because routing has not run this far out."""


class AdmissionMiddleware:
    """Counts the HTTP requests in flight and refuses past the bound with the
    unavailable shape and a `Retry-After`. The count is a plain integer: one
    event loop owns it, and it is read and written with no await in between,
    so nothing interleaves. A socket is not counted: it is held open for as
    long as its subscriber wants it, and a bound on requests in flight that a
    long-lived connection can fill is not a bound on requests."""

    def __init__(self, app: ASGIApp, limit: int, retry_after: timedelta) -> None:
        self.app = app
        self.limit = limit
        self.retry_after = str(max(1, int(retry_after.total_seconds())))
        self.in_flight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in UNBOUNDED_PATHS:
            await self.app(scope, receive, send)
            return
        if self.in_flight >= self.limit:
            OUTCOMES.labels(subsystem="admission", outcome="refused").inc()
            await self.refuse(scope, receive, send)
            return
        OUTCOMES.labels(subsystem="admission", outcome="admitted").inc()
        self.in_flight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.in_flight -= 1

    async def refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        """The refusal is `Unavailable`, presented in the one error envelope.
        A middleware sits outside the handler that translates an exception
        raised in a route, so the refusal is rendered here from the same
        exception and the same envelope the handler would have used, and the
        status and the code are read off the shape rather than written again.
        The `Retry-After` is the one `RateLimited` gets, for the same reason:
        a client that is told to come back is told when."""
        refusal = Unavailable("the process is at its bound of requests in flight")
        response = error_response(
            request_id_of(scope),
            refusal.http_status,
            refusal.code,
            refusal.message,
            {"Retry-After": self.retry_after},
        )
        await response(scope, receive, send)
