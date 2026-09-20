"""Request id middleware: accept or mint, stamp on the scope, echo in the
response, open the server span with it attached, count the request, log it
as one line naming the route template, and answer an unhandled exception
with the envelope while the id is still in hand."""

import logging
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import SpanKind
from starlette.datastructures import Headers, MutableHeaders

from tadas.infra.observability import HTTP_LATENCY, HTTP_REQUESTS, request_id_var
from tadas.om.base import new_id
from tadas.services.api.gateway.envelope import INTERNAL_ERROR, error_response

log = logging.getLogger(__name__)

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

REQUEST_ID_HEADER = "x-request-id"
REQUEST_ID_ATTRIBUTE = "tadas.request_id"

tracer = trace.get_tracer("tadas.services.api")
"""Resolved against whatever provider boot configured; the no-op one otherwise."""


def parse_request_id(value: str | None) -> UUID:
    if value:
        try:
            return UUID(value)
        except ValueError:
            pass
    return new_id()


def request_id_of(scope: Scope) -> UUID:
    return scope["state"]["request_id"]


class QueryStringRedactor(logging.Filter):
    """uvicorn's own lines name a path with its query string, the socket's
    single-use ticket among them; the filter keeps the path and drops the
    rest. Installed on the logger uvicorn writes them to."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                arg.partition("?")[0] if isinstance(arg, str) else arg for arg in record.args
            )
        return True


def route_template_of(scope: Scope) -> str | None:
    """The matched route's full template, prefix included. FastAPI keeps the
    prefixed path on the effective route context it stores in the scope and
    leaves the sub-router's own path on the route; the test pins the label."""
    context = scope.get("fastapi", {}).get("effective_route_context")
    return getattr(context, "path", None) or getattr(scope.get("route"), "path", None)


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        request_id = parse_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id
        method = scope["method"] if scope["type"] == "http" else "WEBSOCKET"
        token = request_id_var.set(str(request_id))
        status = {"code": 0}
        started = time.perf_counter()

        async def send_with_request_id(message: MutableMapping[str, Any]) -> None:
            if message["type"] in ("http.response.start", "websocket.accept"):
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, str(request_id))
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        # The server span is opened here, around everything downstream, so the
        # context the gateway builds reads a real trace id. The route template
        # is only known once routing has run, so the name is finished at the end.
        with tracer.start_as_current_span(
            f"{method} {scope['path']}",
            kind=SpanKind.SERVER,
            attributes={REQUEST_ID_ATTRIBUTE: str(request_id), "url.path": scope["path"]},
        ) as span:
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception:
                # Starlette's own catch-all runs outside this middleware, once
                # the id has left the log context and the span has closed; a
                # response that has not started is answered here instead,
                # with the header, the log line, and the status all carrying
                # the id. One that has started, or a socket, is re-raised.
                if scope["type"] != "http" or status["code"] != 0:
                    raise
                log.exception("unhandled error on %s %s", method, scope["path"])
                response = error_response(request_id, 500, *INTERNAL_ERROR)
                await response(scope, receive, send_with_request_id)
            finally:
                template = route_template_of(scope) or "unmatched"
                span.update_name(f"{method} {template}")
                span.set_attribute("http.route", template)
                if scope["type"] == "http":
                    elapsed = time.perf_counter() - started
                    span.set_attribute("http.response.status_code", status["code"])
                    HTTP_REQUESTS.labels(route=template, method=method, status=status["code"]).inc()
                    HTTP_LATENCY.labels(route=template, method=method).observe(elapsed)
                    # The access line, in place of uvicorn's: the template, so
                    # a query string (the socket ticket rides in one) is never
                    # written out.
                    log.info("%s %s %d %.1fms", method, template, status["code"], elapsed * 1000)
                # Last, after every line this request writes: the access line
                # above carries the id only while the context still holds it.
                request_id_var.reset(token)
