"""The two operator dashboards carry the same panels.

The local one is Grafana's, provisioned into the devx profile; the cloud one
is CloudWatch's, declared in Terraform from a JSON template. What an operator
learns on the local stack is what they see in production, and this test is
what holds the two lists of titles equal.

Latency is the one difference, and it is named here. CloudWatch computes no
percentile from the statistic set a histogram is exported as, so the cloud
widget reads the load balancer's p95 over every route, and its title says so
instead of claiming a per-route line it cannot draw.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAFANA = ROOT / "deployment" / "local" / "grafana" / "dashboards" / "tadas-overview.json"
CLOUD = ROOT / "deployment" / "terraform" / "modules" / "dashboard" / "dashboard.json.tftpl"

CLOUD_TITLE_FOR = {
    "HTTP latency p95 by route": "HTTP latency p95, all routes, at the load balancer",
}
"""A local panel whose cloud widget carries another title, and the one it carries."""


def _grafana_titles() -> list[str]:
    return [panel["title"] for panel in json.loads(GRAFANA.read_text())["panels"]]


def _cloud_titles() -> list[str]:
    # The template is JSON with Terraform interpolations and nothing else;
    # every `${name}` becomes null, and the document parses.
    body = json.loads(re.sub(r"\$\{\w+\}", "null", CLOUD.read_text()))
    return [widget["properties"]["title"] for widget in body["widgets"]]


def test_the_cloud_dashboard_carries_every_local_panel_by_title() -> None:
    local = _grafana_titles()
    cloud = _cloud_titles()
    assert len(local) == 5, "the local dashboard is the five panels an operator asks first"
    expected = [CLOUD_TITLE_FOR.get(title, title) for title in local]
    assert cloud[: len(local)] == expected, "the first cloud widgets are the local panels, in order"


def test_the_cloud_dashboard_adds_one_row_for_the_backing_services() -> None:
    extra = _cloud_titles()[len(_grafana_titles()) :]
    assert extra == [
        "Database CPU and connections",
        "Cache CPU",
        "Queue messages visible and dead",
        "Running tasks",
    ]


def test_the_cloud_dashboard_reads_the_application_metrics_from_the_tadas_namespace() -> None:
    text = CLOUD.read_text()
    # The exporter adds OTelLib to every series, and a schema that leaves out
    # a dimension the series has matches nothing.
    schemas = re.findall(r"SEARCH\('\{Tadas,[^}]*\}", text)
    assert schemas, "the application widgets search the Tadas namespace"
    assert all(schema.startswith("SEARCH('{Tadas,OTelLib,") for schema in schemas)
    for metric in ("tadas_http_requests_total", "tadas_outcomes_total"):
        assert f'MetricName=\\"{metric}\\"' in text


def test_the_cloud_latency_widget_reads_the_load_balancer_p95() -> None:
    body = json.loads(re.sub(r"\$\{\w+\}", "null", CLOUD.read_text()))
    (widget,) = [
        widget
        for widget in body["widgets"]
        if widget["properties"]["title"] == CLOUD_TITLE_FOR["HTTP latency p95 by route"]
    ]
    assert widget["properties"]["stat"] == "p95"
    assert widget["properties"]["metrics"][0][:2] == ["AWS/ApplicationELB", "TargetResponseTime"]
