"""The cloud's stores: CloudWatch Logs Insights over `/tadas/<env>/api`,
CloudWatch metrics in the `Tadas` namespace, X-Ray trace summaries, and
Sentry's REST API under a token. The AWS clients come from an aioboto3
session under a named profile: the investigate role of the environment,
which can read every signal and write nothing.

X-Ray is filtered on the annotation `tadas_request_id`: the collector turns
the span attribute `tadas.request_id` into it only when its X-Ray exporter
lists the attribute under `indexed_attributes`. Without that, no filter by
id exists, and the reader says so instead of guessing from the URL."""

import asyncio
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import aioboto3
import httpx

from tadas.ops.signals import ErrorEventFound, SignalsInterface, TraceFound
from tadas.ops.signals.sentry import find_error_event

NAMESPACE = "Tadas"
REQUEST_ID_ANNOTATION = "tadas_request_id"
QUERY_POLL_SECONDS = 1.0
QUERY_POLL_LIMIT = 30
DEFAULT_LOOKBACK = timedelta(hours=1)


class SessionLike(Protocol):
    """What the impl needs of `aioboto3.Session`; a test hands a fake."""

    def client(self, service_name: str) -> AbstractAsyncContextManager[Any]: ...


def log_group(environment: str) -> str:
    return f"/tadas/{environment}/api"


def insights_query(request_id: str) -> str:
    return (
        f'fields @timestamp, @message | filter request_id = "{request_id}" '
        "| sort @timestamp asc | limit 100"
    )


class SignalsCloudImpl(SignalsInterface):
    def __init__(
        self,
        *,
        environment: str,
        profile: str | None,
        region: str | None,
        sentry_url: str,
        sentry_token: str,
        sentry_org: str,
        session: SessionLike | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        lookback: timedelta = DEFAULT_LOOKBACK,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.environment = environment
        self.profile = profile
        self.region = region
        self.sentry_url = sentry_url.rstrip("/")
        self.sentry_token = sentry_token
        self.sentry_org = sentry_org
        self.lookback = lookback
        self._session: SessionLike = session or cast(
            SessionLike, aioboto3.Session(profile_name=profile, region_name=region)
        )
        self._transport = transport
        self._now = now
        self._sleep = sleep

    async def log_lines(self, request_id: str) -> list[str]:
        now = self._now()
        async with self._session.client("logs") as logs:
            started = await logs.start_query(
                logGroupName=log_group(self.environment),
                startTime=int((now - self.lookback).timestamp()),
                endTime=int(now.timestamp()),
                queryString=insights_query(request_id),
            )
            for _ in range(QUERY_POLL_LIMIT):
                results = await logs.get_query_results(queryId=started["queryId"])
                if results.get("status") in ("Complete", "Failed", "Cancelled", "Timeout"):
                    break
                await self._sleep(QUERY_POLL_SECONDS)
            else:
                results = {"results": []}
        lines: list[str] = []
        for row in results.get("results", []):
            fields = {cell.get("field"): cell.get("value") for cell in row}
            if fields.get("@message") is not None:
                lines.append(str(fields["@message"]))
        return lines

    async def metric_delta(
        self, name: str, labels: Mapping[str, str], since: datetime
    ) -> float | None:
        if any(value.startswith("~") for value in labels.values()):
            # A dimension is exact; there is no series a pattern names here.
            return None
        now = self._now()
        period = max(60, int(((now - since).total_seconds() // 60 + 1) * 60))
        async with self._session.client("cloudwatch") as cloudwatch:
            data = await cloudwatch.get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "m",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": NAMESPACE,
                                "MetricName": name,
                                "Dimensions": [
                                    {"Name": key, "Value": value}
                                    for key, value in sorted(labels.items())
                                ],
                            },
                            "Period": period,
                            "Stat": "Sum",
                        },
                        "ReturnData": True,
                    }
                ],
                StartTime=since,
                EndTime=now,
            )
        values: list[float] = []
        for result in data.get("MetricDataResults", []):
            values.extend(float(v) for v in result.get("Values", []))
        return sum(values) if values else None

    async def trace(self, request_id: str) -> TraceFound | None:
        now = self._now()
        async with self._session.client("xray") as xray:
            summaries = await xray.get_trace_summaries(
                StartTime=now - self.lookback,
                EndTime=now,
                FilterExpression=f'annotation.{REQUEST_ID_ANNOTATION} = "{request_id}"',
            )
        for summary in summaries.get("TraceSummaries", []):
            trace_id = str(summary.get("Id", ""))
            names = tuple(
                str(service.get("Name", ""))
                for service in summary.get("ServiceIds", [])
                if service.get("Name")
            )
            return TraceFound(trace_id=trace_id, span_names=names)
        return None

    async def error_event(self, request_id: str) -> ErrorEventFound | None:
        async with httpx.AsyncClient(transport=self._transport, timeout=10.0) as http:
            return await find_error_event(
                http, self.sentry_url, self.sentry_token, self.sentry_org, request_id
            )

    def describe(self) -> str:
        return (
            f"logs: CloudWatch Logs Insights on {log_group(self.environment)} by request_id; "
            f"metrics: CloudWatch namespace {NAMESPACE}; "
            f"traces: X-Ray by annotation {REQUEST_ID_ANNOTATION} "
            "(the collector must index tadas.request_id; otherwise no trace is found by id); "
            f"errors: Sentry {self.sentry_url} org {self.sentry_org} by tag request_id; "
            f"profile {self.profile or 'default'}, region {self.region or 'default'}"
        )
