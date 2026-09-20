"""The two operator dashboards carry the same panels.

The local one is Grafana's, provisioned into the devx profile; the cloud one
is CloudWatch's, declared in Terraform from a JSON template. What an operator
learns on the local stack is what they see in production, and this test is
what holds the two lists of titles equal.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAFANA = ROOT / "deployment" / "local" / "grafana" / "dashboards" / "tadas-overview.json"
CLOUD = ROOT / "deployment" / "terraform" / "modules" / "dashboard" / "dashboard.json.tftpl"


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
    assert cloud[: len(local)] == local, "the first cloud widgets are the local panels, in order"


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
    assert "SEARCH('{Tadas," in text
    for metric in (
        "tadas_http_requests_total",
        "tadas_http_request_seconds",
        "tadas_outcomes_total",
    ):
        assert f'MetricName=\\"{metric}\\"' in text
