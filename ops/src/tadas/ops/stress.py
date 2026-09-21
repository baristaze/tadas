"""The stress test: the traffic generator with a scenario. A scenario file
names a profile, a duration, a ramp, and a target (a p95 and an error ratio)
stated before the run. The run ramps the workers up linearly, drives the
profile for the duration, then reads the signals back for the window and
passes or fails against the target. The numbers a system is held to are the
system's, and they live in the scenario file, not here."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tadas.ops.profiles import Profile, profile_named
from tadas.ops.report import Report
from tadas.ops.signals import SignalsInterface

REQUESTS_COUNTER = "tadas_http_requests_total"
POLL_SECONDS = 5.0
READBACK_WAIT_SECONDS = 45.0
"""Long enough for the local scrape interval (15 s) twice over and the
collector's batch (5 s) that writes a host process's samples into
Prometheus (deployment/local/otel-collector/collector.yml)."""


@dataclass(frozen=True)
class Target:
    p95_ms: float
    error_ratio: float


@dataclass(frozen=True)
class Scenario:
    name: str
    profile: Profile
    duration_seconds: float
    ramp_seconds: float
    target: Target
    weights: Mapping[str, float]


def parse_scenario(data: Mapping[str, Any]) -> Scenario:
    for key in ("name", "profile", "duration_seconds", "ramp_seconds", "target"):
        if key not in data:
            raise ValueError(f"scenario is missing {key!r}")
    target = data["target"]
    if not isinstance(target, Mapping) or "p95_ms" not in target or "error_ratio" not in target:
        raise ValueError("scenario target needs p95_ms and error_ratio")
    weights = data.get("weights") or {}
    if not isinstance(weights, Mapping):
        raise ValueError("scenario weights must be a mapping")
    duration = float(data["duration_seconds"])
    ramp = float(data["ramp_seconds"])
    if duration <= 0 or ramp < 0 or ramp > duration:
        raise ValueError("duration_seconds must be positive and ramp_seconds within it")
    return Scenario(
        name=str(data["name"]),
        profile=profile_named(str(data["profile"])),
        duration_seconds=duration,
        ramp_seconds=ramp,
        target=Target(p95_ms=float(target["p95_ms"]), error_ratio=float(target["error_ratio"])),
        weights={str(k): float(v) for k, v in weights.items()},
    )


def load_scenario(path: Path) -> Scenario:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} is not a scenario mapping")
    return parse_scenario(data)


@dataclass(frozen=True)
class Readback:
    """What the signals said about the window: how many requests the
    platform counted and how many of them it answered with a 5xx. None when
    the store had nothing for the window."""

    requests: float | None
    server_errors: float | None

    @property
    def error_ratio(self) -> float | None:
        if not self.requests:
            return None
        return (self.server_errors or 0.0) / self.requests


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: tuple[str, ...]

    def text(self, scenario: Scenario, report: Report, readback: Readback) -> str:
        lines = [
            f"stress {scenario.name}: profile {scenario.profile.name}, "
            f"{scenario.duration_seconds:.0f}s with a {scenario.ramp_seconds:.0f}s ramp",
            f"target: p95 <= {scenario.target.p95_ms:.0f} ms, "
            f"error ratio <= {scenario.target.error_ratio:.4f}",
            f"measured: p95 {report.p95_ms:.1f} ms, error ratio {report.error_ratio:.4f} "
            f"over {report.requests} requests, {report.sessions.completed} sessions completed",
            "signals: "
            + (
                f"{readback.requests:.0f} requests counted, {readback.server_errors or 0:.0f} "
                f"server errors (ratio {readback.error_ratio or 0:.4f})"
                if readback.requests
                else "nothing counted for the window"
            ),
            ("PASS" if self.passed else "FAIL")
            + (": " + "; ".join(self.reasons) if self.reasons else ""),
        ]
        return "\n".join(lines) + "\n"


def verdict(scenario: Scenario, report: Report, readback: Readback) -> Verdict:
    """Pass when the generator's p95 and error ratio meet the target, the
    platform counted the window, and its own 5xx ratio meets the target too.
    A run that made no requests fails: it proved nothing."""
    reasons: list[str] = []
    if report.requests == 0:
        reasons.append("no requests were made")
    if report.p95_ms > scenario.target.p95_ms:
        reasons.append(f"p95 {report.p95_ms:.1f} ms over {scenario.target.p95_ms:.0f} ms")
    if report.error_ratio > scenario.target.error_ratio:
        reasons.append(
            f"error ratio {report.error_ratio:.4f} over {scenario.target.error_ratio:.4f}"
        )
    if not readback.requests:
        reasons.append("the platform counted no requests for the window")
    elif (readback.error_ratio or 0.0) > scenario.target.error_ratio:
        reasons.append(
            f"the platform's 5xx ratio {readback.error_ratio:.4f} over "
            f"{scenario.target.error_ratio:.4f}"
        )
    return Verdict(passed=not reasons, reasons=tuple(reasons))


async def read_back(signals: SignalsInterface, since: datetime) -> Readback:
    requests = await signals.metric_delta(REQUESTS_COUNTER, {}, since)
    errors = await signals.metric_delta(REQUESTS_COUNTER, {"status": "~5.."}, since)
    return Readback(requests=requests, server_errors=errors)


def window_start(report: Report) -> datetime:
    return report.started_at if report.started_at.tzinfo else report.started_at.replace(tzinfo=UTC)
