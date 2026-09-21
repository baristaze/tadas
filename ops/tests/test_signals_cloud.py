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


def series(**dimensions: str) -> dict[str, Any]:
    labels = {"environment": "staging", "service": "api", "method": "GET"} | dimensions
    return {
        "Namespace": "Tadas",
        "MetricName": "tadas_http_requests_total",
        "Dimensions": [{"Name": k, "Value": v} for k, v in labels.items()],
    }


class FakeCloudWatch:
    """Lists its series two pages at a time and answers every query with the
    values the series was given; a series is known by its route and status."""

    def __init__(self) -> None:
        self.metrics = [
            series(route="/v1/tasks", status="200"),
            series(route="/v1/tasks", status="201"),
            series(route="/v1/tasks", status="503"),
            series(route="/v1/me", status="500"),
        ]
        self.values = {
            ("/v1/tasks", "200"): [3.0, 4.0],
            ("/v1/tasks", "201"): [2.0],
            ("/v1/tasks", "503"): [1.0],
            ("/v1/me", "500"): [5.0],
        }
        self.listed: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []

    async def list_metrics(self, **kwargs: Any) -> dict[str, Any]:
        self.listed.append(kwargs)
        start = int(kwargs.get("NextToken", "0"))
        page = self.metrics[start : start + 2]
        more = start + 2 < len(self.metrics)
        return {"Metrics": page} | ({"NextToken": str(start + 2)} if more else {})

    async def get_metric_data(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        results = []
        for query in kwargs["MetricDataQueries"]:
            dims = {d["Name"]: d["Value"] for d in query["MetricStat"]["Metric"]["Dimensions"]}
            values = self.values.get((dims["route"], dims["status"]), [])
            results.append({"Id": query["Id"], "Values": values})
        return {"MetricDataResults": results}


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


async def test_the_metric_delta_sums_every_series_of_the_environment() -> None:
    """The collector exports each series with every label as a dimension, so
    a query naming none finds nothing: the series are listed, then summed."""
    session = FakeSession()
    delta = await reader(session).metric_delta(
        "tadas_http_requests_total", {}, NOW - timedelta(minutes=3)
    )
    assert delta == 15.0
    assert [call.get("NextToken") for call in session.cloudwatch.listed] == [None, "2"]
    assert session.cloudwatch.listed[0]["Dimensions"] == [
        {"Name": "environment", "Value": "staging"}
    ]
    call = session.cloudwatch.calls[0]
    stat = call["MetricDataQueries"][0]["MetricStat"]
    assert stat["Metric"]["Namespace"] == "Tadas"
    assert stat["Stat"] == "Sum" and stat["Period"] == 240
    assert call["StartTime"] == NOW - timedelta(minutes=3) and call["EndTime"] == NOW


async def test_the_metric_delta_picks_series_by_exact_label_or_pattern() -> None:
    session = FakeSession()
    impl = reader(session)
    exact = await impl.metric_delta("tadas_http_requests_total", {"status": "201"}, NOW)
    assert exact == 2.0
    server_errors = await impl.metric_delta("tadas_http_requests_total", {"status": "~5.."}, NOW)
    assert server_errors == 6.0
    both = await impl.metric_delta(
        "tadas_http_requests_total", {"route": "/v1/tasks", "status": "~5.."}, NOW
    )
    assert both == 1.0


async def test_no_matching_series_is_none_and_a_quiet_one_is_zero() -> None:
    session = FakeSession()
    impl = reader(session)
    assert await impl.metric_delta("tadas_http_requests_total", {"status": "~4.."}, NOW) is None
    session.cloudwatch.values.clear()
    assert await impl.metric_delta("tadas_http_requests_total", {}, NOW) == 0.0


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
