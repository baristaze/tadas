"""`tadas-ops`: traffic, stress, signals check, and size, each against one
named environment. Exit 0 when the run did what was asked, 1 when a stress
target was missed or a reader found nothing, 2 for a bad invocation."""

import argparse
import asyncio
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from tadas.client.client import ApiClient
from tadas.ops.environments import Environment, load_environment
from tadas.ops.profiles import PROFILES, profile_named
from tadas.ops.report import Report
from tadas.ops.signals import Readback, SignalsInterface
from tadas.ops.signals.cloud import SignalsCloudImpl
from tadas.ops.signals.local import SignalsLocalImpl
from tadas.ops.stress import (
    READBACK_WAIT_SECONDS,
    load_scenario,
    read_back,
    verdict,
    window_start,
)
from tadas.ops.traffic import OPERATOR_APP, app_version, run_traffic

OK, FAILED, USAGE = 0, 1, 2


def file_lines(path: Path | None) -> Callable[[], Iterable[str]]:
    def read() -> Iterable[str]:
        return path.read_text().splitlines() if path and path.is_file() else []

    return read


def signals_for(env: Environment, *, log_file: Path | None = None) -> SignalsInterface:
    """The reader an environment gets: the cloud impl for the deployed names,
    the local impl for everything else."""
    if env.is_cloud:
        if not env.error_tracker_url or not env.error_tracker_token:
            raise ValueError(f"environment {env.name!r} names no error tracker url and token")
        return SignalsCloudImpl(
            environment=env.name,
            profile=env.aws_profile,
            region=env.aws_region,
            sentry_url=env.error_tracker_url,
            sentry_token=env.error_tracker_token,
            sentry_org=env.error_tracker_org,
        )
    if not (env.prometheus_url and env.jaeger_url and env.error_tracker_url):
        raise ValueError(f"environment {env.name!r} names no Prometheus, Jaeger, and error tracker")
    return SignalsLocalImpl(
        prometheus_url=env.prometheus_url,
        jaeger_url=env.jaeger_url,
        error_tracker_url=env.error_tracker_url,
        error_tracker_token=env.error_tracker_token or "",
        error_tracker_org=env.error_tracker_org,
        logs=file_lines(log_file),
    )


async def check_signals(
    signals: SignalsInterface, request_id: str, since: datetime, metric: str
) -> Readback:
    return Readback(
        request_id=request_id,
        log_lines=await signals.log_lines(request_id),
        metric_delta=await signals.metric_delta(metric, {}, since),
        trace=await signals.trace(request_id),
        error_event=await signals.error_event(request_id),
    )


def readback_text(readback: Readback, metric: str) -> str:
    lines = [f"request {readback.request_id}"]
    lines.append(
        f"  log lines: {len(readback.log_lines)} found"
        + (f"; first: {readback.log_lines[0][:120]}" if readback.log_lines else "")
    )
    lines.append(
        f"  metric {metric}: "
        + ("no series" if readback.metric_delta is None else f"moved by {readback.metric_delta:g}")
    )
    lines.append(
        "  trace: "
        + (
            f"{readback.trace.trace_id} ({len(readback.trace.span_names)} spans)"
            if readback.trace
            else "not found"
        )
    )
    lines.append(
        "  error event: "
        + (
            f"{readback.error_event.event_id} in issue {readback.error_event.issue_id} "
            f"({readback.error_event.title})"
            if readback.error_event
            else "not found"
        )
    )
    return "\n".join(lines) + "\n"


# Commands


async def traffic_command(args: argparse.Namespace) -> tuple[int, Report]:
    env = load_environment(args.env)
    profile = profile_named(args.profile)
    result = await run_traffic(
        env, profile, duration_seconds=args.duration, orgs=args.orgs, ramp_seconds=args.ramp
    )
    sys.stdout.write(result.report.table())
    return (OK if result.report.sessions.completed > 0 else FAILED), result.report


async def stress_command(args: argparse.Namespace) -> tuple[int, Report]:
    env = load_environment(args.env)
    scenario = load_scenario(Path(args.scenario))
    result = await run_traffic(
        env,
        scenario.profile,
        duration_seconds=scenario.duration_seconds,
        orgs=args.orgs,
        ramp_seconds=scenario.ramp_seconds,
    )
    report = result.report
    sys.stdout.write(report.table())
    signals = signals_for(env)
    since = window_start(report)
    # The scrape lags the run; the readback waits for it to catch up.
    deadline = datetime.now(UTC) + timedelta(seconds=READBACK_WAIT_SECONDS)
    readback = await read_back(signals, since)
    while (readback.requests or 0) < report.requests and datetime.now(UTC) < deadline:
        await asyncio.sleep(5)
        readback = await read_back(signals, since)
    outcome = verdict(scenario, report, readback)
    sys.stdout.write(outcome.text(scenario, report, readback))
    return (OK if outcome.passed else FAILED), report


def write_report(args: argparse.Namespace, outcome: tuple[int, Report]) -> int:
    """The JSON file a `--report` asked for, written once the loop is done."""
    code, report = outcome
    if args.report:
        Path(args.report).write_text(report.to_json())
        print(f"wrote {args.report}")
    return code


async def signals_command(args: argparse.Namespace) -> int:
    env = load_environment(args.env)
    signals = signals_for(env, log_file=Path(args.log_file) if args.log_file else None)
    print(signals.describe())
    since = datetime.now(UTC) - timedelta(minutes=args.since_minutes)
    readback = await check_signals(signals, args.request_id, since, args.metric)
    sys.stdout.write(readback_text(readback, args.metric))
    found = bool(readback.log_lines or readback.trace or readback.error_event)
    return OK if found else FAILED


async def size_command(
    args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None = None
) -> int:
    env = load_environment(args.env)
    if not env.operator_email or not env.operator_password:
        print(f"environment {env.name!r} names no operator", file=sys.stderr)
        return USAGE
    async with ApiClient(
        env.api_url, app=OPERATOR_APP, app_version=app_version(), transport=transport
    ) as client:
        login = await client.login(env.operator_email, env.operator_password)
        size: dict[str, Any] = await client.request("GET", "/v1/admin/size", token=login.token)
    for key, value in size.items():
        print(f"{key:<24} {value}")
    return OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tadas-ops")
    sub = parser.add_subparsers(dest="command", required=True)

    p_traffic = sub.add_parser("traffic", help="drive realistic sessions at a profile")
    p_traffic.add_argument("--env", required=True, help="local, staging, or production")
    p_traffic.add_argument("--profile", default="light", choices=list(PROFILES))
    p_traffic.add_argument("--duration", type=float, help="seconds; the profile's when absent")
    p_traffic.add_argument(
        "--orgs",
        type=int,
        help="tenants to provision through the operator plane; 0 drives the seeded org",
    )
    p_traffic.add_argument("--ramp", type=float, default=0.0, help="seconds to reach concurrency")
    p_traffic.add_argument("--report", help="write the report as JSON here")

    p_stress = sub.add_parser("stress", help="run a scenario and judge it against its target")
    p_stress.add_argument("--scenario", required=True, help="ops/stress/<name>.yaml")
    p_stress.add_argument("--env", default="local")
    p_stress.add_argument("--orgs", type=int)
    p_stress.add_argument("--report")

    p_signals = sub.add_parser("signals", help="read the signals back")
    signals_sub = p_signals.add_subparsers(dest="signals_command", required=True)
    p_check = signals_sub.add_parser("check", help="what each reader finds for one request id")
    p_check.add_argument("--env", required=True)
    p_check.add_argument("--request-id", required=True)
    p_check.add_argument("--since-minutes", type=int, default=60)
    p_check.add_argument("--metric", default="tadas_http_requests_total")
    p_check.add_argument("--log-file", help="the process's captured log, for the local reader")

    p_size = sub.add_parser("size", help="the platform's size as the operator plane reports it")
    p_size.add_argument("--env", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "traffic":
            return write_report(args, asyncio.run(traffic_command(args)))
        if args.command == "stress":
            return write_report(args, asyncio.run(stress_command(args)))
        if args.command == "signals":
            return asyncio.run(signals_command(args))
        return asyncio.run(size_command(args))
    except (ValueError, FileNotFoundError) as error:
        print(f"tadas-ops: {error}", file=sys.stderr)
        return USAGE


if __name__ == "__main__":
    sys.exit(main())
