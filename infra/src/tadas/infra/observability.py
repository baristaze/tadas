"""Logging with the request-id filter, error reporting, tracing, and the
process metrics. Configured once at the app container's boot and never per
module."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import sentry_sdk
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

request_id_var: ContextVar[str | None] = ContextVar("tadas_request_id", default=None)
"""Set at the entry point that builds the context, so log lines get it for free.
The authoritative request id is still the field on OpContext."""

HTTP_REQUESTS = Counter(
    "tadas_http_requests_total",
    "HTTP requests by route template and status",
    ["route", "method", "status"],
)
HTTP_LATENCY = Histogram(
    "tadas_http_request_seconds", "HTTP request latency by route template", ["route", "method"]
)
OUTCOMES = Counter(
    "tadas_outcomes_total",
    "Outcomes of queues, caches, rate limits, and sweeps",
    ["subsystem", "outcome"],
)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line)


def configure_logging(level: str, json_logs: bool) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(RequestIdFilter())
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s [%(request_id)s] %(name)s: %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(level.upper())


def configure_error_reporting(
    dsn: str | None, environment: str, service_name: str, release: str | None = None
) -> None:
    """Sentry-compatible reporting (GlitchTip locally), only when a DSN is set.
    Unhandled exceptions and ERROR log records become events, tagged with the
    service and the request id; traces stay with OpenTelemetry."""
    if not dsn:
        return

    def tag_request_id(event: Any, hint: Any) -> Any:
        request_id = request_id_var.get()
        if request_id:
            event.setdefault("tags", {})["request_id"] = request_id
        return event

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=f"{service_name}@{release}" if release else None,
        server_name=service_name,
        traces_sample_rate=0.0,
        send_default_pii=False,
        before_send=tag_request_id,
    )
    sentry_sdk.set_tag("service", service_name)


def configure_tracing(endpoint: str | None, service_name: str) -> None:
    """The provider is configured only when an endpoint is set; otherwise the
    no-op tracer runs and the code paths stay identical."""
    if not endpoint:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces"))
    )
    trace.set_tracer_provider(provider)


def current_trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.trace_id, "032x")


def metrics_exposition() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
