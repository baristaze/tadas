"""Request id middleware: accept or mint, stamp on the scope, echo in the
response, attach to the log context and the span; and the request metrics."""

import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import UUID

from opentelemetry import trace
from starlette.datastructures import Headers, MutableHeaders

from tadas.infra.observability import HTTP_LATENCY, HTTP_REQUESTS, request_id_var
from tadas.om.base import new_id

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

REQUEST_ID_HEADER = "x-request-id"


def parse_request_id(value: str | None) -> UUID:
    if value:
        try:
            return UUID(value)
        except ValueError:
            pass
    return new_id()


def request_id_of(scope: Scope) -> UUID:
    return scope["state"]["request_id"]


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        request_id = parse_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(str(request_id))
        trace.get_current_span().set_attribute("tadas.request_id", str(request_id))
        status = {"code": 0}
        started = time.perf_counter()

        async def send_with_request_id(message: MutableMapping[str, Any]) -> None:
            if message["type"] in ("http.response.start", "websocket.accept"):
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, str(request_id))
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
            if scope["type"] == "http":
                route = scope.get("route")
                template = getattr(route, "path", None) or "unmatched"
                method = scope["method"]
                HTTP_REQUESTS.labels(route=template, method=method, status=status["code"]).inc()
                HTTP_LATENCY.labels(route=template, method=method).observe(
                    time.perf_counter() - started
                )
