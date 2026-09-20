"""The scenario parser and the verdict: a target stated before the run, a
pass only when the generator and the platform's own count both meet it."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tadas.ops.report import Report, Sample, Sessions
from tadas.ops.stress import Readback, load_scenario, parse_scenario, verdict

HERE = Path(__file__).parent
AT = datetime(2026, 9, 20, tzinfo=UTC)


def test_the_smoke_scenario_parses() -> None:
    scenario = load_scenario(HERE / "smoke.yaml")
    assert scenario.name == "smoke" and scenario.profile.name == "light"
    assert (scenario.duration_seconds, scenario.ramp_seconds) == (30.0, 5.0)
    assert (scenario.target.p95_ms, scenario.target.error_ratio) == (500.0, 0.01)
    assert scenario.weights == {"full": 1.0}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"name": "x"}, "missing 'profile'"),
        (
            {"name": "x", "profile": "light", "duration_seconds": 1, "ramp_seconds": 0},
            "missing 'target'",
        ),
        (
            {
                "name": "x",
                "profile": "light",
                "duration_seconds": 1,
                "ramp_seconds": 0,
                "target": {},
            },
            "p95_ms and error_ratio",
        ),
        (
            {
                "name": "x",
                "profile": "light",
                "duration_seconds": 10,
                "ramp_seconds": 20,
                "target": {"p95_ms": 1, "error_ratio": 0},
            },
            "ramp_seconds within",
        ),
        (
            {
                "name": "x",
                "profile": "gentle",
                "duration_seconds": 10,
                "ramp_seconds": 0,
                "target": {"p95_ms": 1, "error_ratio": 0},
            },
            "unknown profile",
        ),
    ],
)
def test_a_bad_scenario_is_refused_by_name(data: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_scenario(data)


def report_with(p95: float, errors: int, total: int = 100) -> Report:
    samples = [Sample("/v1/tasks", "GET", 503 if i < errors else 200, p95) for i in range(total)]
    return Report.of(
        samples,
        environment="local",
        profile="light",
        started_at=AT,
        duration_seconds=30,
        sessions=Sessions(completed=4),
    )


def test_the_verdict_passes_only_within_the_target_on_both_sides() -> None:
    scenario = load_scenario(HERE / "smoke.yaml")
    assert verdict(scenario, report_with(120.0, 0), Readback(100, 0)).passed
    slow = verdict(scenario, report_with(900.0, 0), Readback(100, 0))
    assert not slow.passed and slow.reasons == ("p95 900.0 ms over 500 ms",)
    failing = verdict(scenario, report_with(10.0, 5), Readback(100, 5))
    assert not failing.passed and len(failing.reasons) == 2
    unread = verdict(scenario, report_with(10.0, 0), Readback(None, None))
    assert unread.reasons == ("the platform counted no requests for the window",)
    empty = verdict(scenario, report_with(10.0, 0, total=0), Readback(None, None))
    assert "no requests were made" in empty.reasons
    text = failing.text(scenario, report_with(10.0, 5), Readback(100, 5))
    assert text.startswith("stress smoke:") and "FAIL: " in text and "100 requests counted" in text
