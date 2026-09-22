"""The scenario parser and the verdict: a target stated before the run, a
pass only when the generator and the platform's own count both meet it."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tadas.ops.report import Report, Sample, Sessions
from tadas.ops.stress import (
    Readback,
    load_scenario,
    parse_scenario,
    verdict,
    with_duration,
)

HERE = Path(__file__).parent
AT = datetime(2026, 9, 20, tzinfo=UTC)


def test_the_smoke_scenario_parses() -> None:
    scenario = load_scenario(HERE / "smoke.yaml")
    assert scenario.name == "smoke" and scenario.profile.name == "light"
    assert (scenario.duration_seconds, scenario.ramp_seconds) == (30.0, 5.0)
    assert (scenario.target.p95_ms, scenario.target.error_ratio) == (500.0, 0.01)
    assert scenario.weights == {"full": 1.0}


def test_every_scenario_a_run_can_name_parses() -> None:
    """The files under ops/stress, not the fixture beside these tests: a
    scenario that does not parse is found here and not on the environment."""
    folder = HERE.parent / "stress"
    scenarios = {load_scenario(path).name: path.name for path in sorted(folder.glob("*.yaml"))}
    assert scenarios == {"smoke": "smoke.yaml", "staging": "staging.yaml"}
    staging = load_scenario(folder / "staging.yaml")
    assert staging.profile.name == "regular"
    assert (staging.duration_seconds, staging.ramp_seconds) == (180.0, 30.0)
    assert (staging.target.p95_ms, staging.target.error_ratio) == (900.0, 0.01)


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


def test_a_named_duration_shortens_the_run_and_its_ramp_and_moves_no_target() -> None:
    """A caller may run a scenario's shape over a shorter window; the target
    it is judged against is still the file's."""
    scenario = load_scenario(HERE / "smoke.yaml")
    shorter = with_duration(scenario, 10)
    assert (shorter.duration_seconds, shorter.ramp_seconds) == (10.0, 5.0)
    assert with_duration(scenario, 3).ramp_seconds == 3.0  # a ramp is never past the run
    assert shorter.target == scenario.target and shorter.profile == scenario.profile
    with pytest.raises(ValueError, match="duration must be positive"):
        with_duration(scenario, 0)


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


def test_the_target_judges_the_working_requests_and_not_the_sign_ins() -> None:
    """Sign-in verifies a password on purpose and is the slowest route the
    generator calls; the run reports it beside the verdict instead of mixing
    it into the number the target holds."""
    scenario = load_scenario(HERE / "smoke.yaml")  # target: p95 500 ms
    samples = [Sample("/v1/tasks", "GET", 200, 10.0) for _ in range(100)]
    samples += [Sample("/v1/auth/login", "POST", 200, 2500.0) for _ in range(4)]
    report = Report.of(
        samples,
        environment="local",
        profile="light",
        started_at=AT,
        duration_seconds=30,
        sessions=Sessions(completed=4),
    )
    outcome = verdict(scenario, report, Readback(104, 0))
    assert outcome.passed and outcome.reasons == ()
    text = outcome.text(scenario, report, Readback(104, 0))
    assert "p95 10.0 ms over 100 working requests" in text
    assert "beside it: 4 sign-ins and sign-outs, p50 2500.0 ms, p95 2500.0 ms" in text


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


def test_a_run_without_an_error_tracker_still_passes_on_what_it_read() -> None:
    """The verdict holds a run to the request counter and the 5xx count, so
    an environment that names no tracker still passes; the text says the leg
    was not read rather than leaving it out."""
    scenario = load_scenario(HERE / "smoke.yaml")
    report = report_with(120.0, 0)
    untracked = Readback(100, 0, error_events_read=False)
    outcome = verdict(scenario, report, untracked)
    assert outcome.passed and outcome.reasons == ()
    text = outcome.text(scenario, report, untracked)
    assert "error events: not read, the environment names no error tracker" in text
    assert text.rstrip().endswith("PASS")
    assert "not read" not in outcome.text(scenario, report, Readback(100, 0))
