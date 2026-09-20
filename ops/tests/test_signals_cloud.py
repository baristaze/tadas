"""The cloud readers over a fake aioboto3 session and a fake Sentry: the
calls they make and what they make of the answers."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from tadas.ops.signals.cloud import SignalsCloudImpl, insights_query, log_group

RID = "11111111-2222-7333-8444-555555555555"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class FakeLogs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.polls = 0

    async def start_query(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("start_query", kwargs))
        return {"queryId": "q1"}

    async def get_query_results(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_query_results", kwargs))
        self.polls += 1
        if self.polls == 1:
            return {"status": "Running", "results": []}
        return {
            "status": "Complete",
            "results": [
                [{"field": "@timestamp", "value": "t"}, {"field": "@message", "value": "line one"}],
                [{"field": "@message", "value": "line two"}],
            ],
        }


class FakeCloudWatch:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def get_metric_data(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"MetricDataResults": [{"Id": "m", "Values": [3.0, 4.0]}]}


class FakeXRay:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def get_trace_summaries(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if RID not in kwargs["FilterExpression"]:
            return {"TraceSummaries": []}
        return {
            "TraceSummaries": [{"Id": "1-abc", "ServiceIds": [{"Name": "api"}, {"Name": "rds"}]}]
        }


class FakeSession:
    def __init__(self) -> None:
        self.logs = FakeLogs()
        self.cloudwatch = FakeCloudWatch()
        self.xray = FakeXRay()
        self.opened: list[str] = []

    def client(self, service_name: str):
        self.opened.append(service_name)
        fake = {"logs": self.logs, "cloudwatch": self.cloudwatch, "xray": self.xray}[service_name]

        @asynccontextmanager
        async def open():
            yield fake

        return open()


def sentry(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer stok"
    if request.url.path == "/api/0/organizations/acme/issues/":
        return httpx.Response(200, json=[{"id": 99, "title": "boom"}])
    if request.url.path == "/api/0/issues/99/events/":
        return httpx.Response(200, json=[{"id": "e1", "tags": {"request_id": RID}}])
    return httpx.Response(404)


def reader(session: FakeSession) -> SignalsCloudImpl:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    impl = SignalsCloudImpl(
        environment="staging",
        profile="tadas-staging-investigate",
        region="us-east-1",
        sentry_url="https://sentry.example.test",
        sentry_token="stok",
        sentry_org="acme",
        session=session,
        transport=httpx.MockTransport(sentry),
        now=lambda: NOW,
        sleep=sleep,
    )
    impl.slept = slept  # type: ignore[attr-defined]
    return impl


async def test_log_lines_run_an_insights_query_and_poll_it_to_completion() -> None:
    session = FakeSession()
    impl = reader(session)
    lines = await impl.log_lines(RID)
    assert lines == ["line one", "line two"]
    start = session.logs.calls[0][1]
    assert start["logGroupName"] == log_group("staging") == "/tadas/staging/api"
    assert (
        start["queryString"] == insights_query(RID)
        and f'request_id = "{RID}"' in start["queryString"]
    )
    assert start["endTime"] - start["startTime"] == 3600
    assert [c[0] for c in session.logs.calls] == [
        "start_query",
        "get_query_results",
        "get_query_results",
    ]
    assert impl.slept == [1.0]  # type: ignore[attr-defined]


async def test_the_metric_delta_sums_the_namespace_metric_over_the_window() -> None:
    session = FakeSession()
    delta = await reader(session).metric_delta(
        "tadas_http_requests_total",
        {"route": "/v1/tasks", "status": "201"},
        NOW - timedelta(minutes=3),
    )
    assert delta == 7.0
    call = session.cloudwatch.calls[0]
    stat = call["MetricDataQueries"][0]["MetricStat"]
    assert stat["Metric"]["Namespace"] == "Tadas"
    assert stat["Metric"]["Dimensions"] == [
        {"Name": "route", "Value": "/v1/tasks"},
        {"Name": "status", "Value": "201"},
    ]
    assert stat["Stat"] == "Sum" and stat["Period"] == 240
    assert call["StartTime"] == NOW - timedelta(minutes=3) and call["EndTime"] == NOW
    assert await reader(session).metric_delta("c", {"status": "~5.."}, NOW) is None


async def test_the_trace_is_filtered_on_the_annotation() -> None:
    session = FakeSession()
    found = await reader(session).trace(RID)
    assert found is not None and found.trace_id == "1-abc" and found.span_names == ("api", "rds")
    assert session.xray.calls[0]["FilterExpression"] == f'annotation.tadas_request_id = "{RID}"'
    assert await reader(session).trace("missing") is None
    assert "annotation tadas_request_id" in reader(session).describe()


async def test_the_error_event_reads_sentry_under_the_token() -> None:
    found = await reader(FakeSession()).error_event(RID)
    assert found is not None and (found.event_id, found.issue_id, found.title) == (
        "e1",
        "99",
        "boom",
    )
