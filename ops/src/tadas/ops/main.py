"""`tadas-ops`: traffic, stress, signals check, size, and token, each against
one named environment. Exit 0 when the run did what was asked, 1 when a
stress target was missed or a reader found nothing, 2 for a bad invocation
or a credential the operator plane refused."""

import argparse
import asyncio
import getpass
import json
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import aioboto3
import httpx

from tadas.client.client import ApiClient, ApiError
from tadas.client.schema import OrgPageView, UserPageView
from tadas.ops.environments import (
    CLOUD_ENVIRONMENTS,
    Environment,
    load_environment,
    ops_file,
    repository_root,
    write_value,
)
from tadas.ops.profiles import PROFILES, profile_named
from tadas.ops.report import Report
from tadas.ops.signals import Readback, SignalsInterface
from tadas.ops.signals.cloud import SessionLike, SignalsCloudImpl
from tadas.ops.signals.local import SignalsLocalImpl
from tadas.ops.stress import (
    READBACK_WAIT_SECONDS,
    load_scenario,
    read_back,
    verdict,
    window_start,
)
from tadas.ops.traffic import (
    OPERATOR_APP,
    TokenRefused,
    app_version,
    is_run_tenant,
    run_traffic,
)

OK, FAILED, USAGE = 0, 1, 2


def file_lines(path: Path | None) -> Callable[[], Iterable[str]]:
    def read() -> Iterable[str]:
        return path.read_text().splitlines() if path and path.is_file() else []

    return read


def signals_for(env: Environment, *, log_file: Path | None = None) -> SignalsInterface:
    """The reader an environment gets: the cloud impl for the deployed names,
    the local impl for everything else. A deployed environment reads its logs,
    metrics, and traces out of its own account and needs no error tracker; one
    that names none reports the error event as not read. Locally the tracker
    is part of the stack, so an environment missing it is a broken stack and
    is refused."""
    if env.is_cloud:
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
        error_events_read=signals.reads_error_events,
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
    if readback.error_event:
        event = (
            f"{readback.error_event.event_id} in issue {readback.error_event.issue_id} "
            f"({readback.error_event.title})"
        )
    elif not readback.error_events_read:
        event = "not read, the environment names no error tracker"
    else:
        event = "not found"
    lines.append(f"  error event: {event}")
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


async def run_tenants(client: ApiClient) -> tuple[int, int]:
    """The tenants traffic runs created that are still live, and their
    people: every page of the orgs, the ones named for a run, and every page
    of each one's members."""
    orgs = users = 0
    cursor: str | None = None
    while True:
        params: dict[str, object] = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = OrgPageView.model_validate(
            await client.request("GET", "/v1/admin/orgs", params=params)
        )
        for org in page.items:
            if not is_run_tenant(org.slug) or org.deleted_at is not None:
                continue
            orgs += 1
            members: str | None = None
            while True:
                people: UserPageView = await client.admin_members(org.id, cursor=members)
                users += len(people.items)
                members = people.next_cursor
                if not members:
                    break
        cursor = page.next_cursor
        if not cursor:
            return orgs, users


async def size_command(
    args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None = None
) -> int:
    """The platform's size as the first responder reads it before an
    escalation: the tenants and users the traffic generator created for its
    runs are left out, since they are the team's own traffic."""
    env = load_environment(args.env)
    if not env.operator_token:
        print(
            f"environment {env.name!r} holds no operator token; write one with "
            f"`uv run tadas-ops token --env {env.name} --identity operator`",
            file=sys.stderr,
        )
        return USAGE
    async with ApiClient(
        env.api_url,
        app=OPERATOR_APP,
        app_version=app_version(),
        token=env.operator_token,
        transport=transport,
    ) as client:
        try:
            size = await client.admin_size()
            run_orgs, run_users = await run_tenants(client)
        except ApiError as error:
            if error.status == 401:
                raise TokenRefused(env, "operator") from None
            raise
    values = size.model_dump()
    values["tenants"] = max(size.tenants - run_orgs, 0)
    values["users"] = max(size.users - run_users, 0)
    for key, value in values.items():
        print(f"{key:<24} {value}")
    print(
        f"{'traffic run tenants':<24} {run_orgs} left out ({run_users} users); "
        "their tasks and events stay in the day's counts"
    )
    return OK


def sso_profile_of(env_name: str) -> str:
    """The person's own Identity Center profile for the environment, from
    deployment/cloud/environments.json."""
    root = repository_root()
    if root is None:
        raise ValueError(
            "run this from the tadas checkout; it reads deployment/cloud/environments.json"
        )
    layout = json.loads((root / "deployment" / "cloud" / "environments.json").read_text())
    return str(layout["environments"][env_name]["sso_profile"])


async def read_provisioner_token(env: Environment, profile: str | None = None) -> str:
    """The token the grant job wrote into `tadas-<env>-provisioner-token`,
    read under the person's own sign-in: the Identity Center profile by
    default, or the one named (production's sign-in reads nothing secret,
    so there it is the power or the administrator profile). Never an
    investigate profile: the investigate role is denied every secret value,
    and an agent never holds this token's source."""
    chosen = profile or sso_profile_of(env.name)
    if chosen.endswith("-investigate"):
        raise ValueError(
            f"{chosen} is an agent's read-only profile and reads no secret; "
            "copy the provisioner's token under your own sign-in (--profile)"
        )
    session = cast(
        SessionLike,
        aioboto3.Session(profile_name=chosen, region_name=env.aws_region),
    )
    async with session.client("secretsmanager") as secrets:
        answer = await secrets.get_secret_value(SecretId=f"tadas-{env.name}-provisioner-token")
    token = str(answer.get("SecretString") or "")
    if not token:
        raise ValueError(
            f"tadas-{env.name}-provisioner-token holds no token yet; dispatch grant-operator.yml "
            "with mint_token: provisioner first"
        )
    return token


async def mint_operator_token(
    env: Environment, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """A person's `read` operator token: the email, the password, and the
    TOTP code are asked for here, in the person's own terminal, and go only
    to the sign-in; what is kept is the token the mint route answers."""
    email = (await asyncio.to_thread(input, "operator email: ")).strip()
    password = await asyncio.to_thread(getpass.getpass, "password: ")
    code = (await asyncio.to_thread(getpass.getpass, "TOTP code: ")).strip()
    async with ApiClient(
        env.api_url, app=OPERATOR_APP, app_version=app_version(), transport=transport
    ) as client:
        login = await client.request(
            "POST",
            "/v1/auth/login",
            json={"email": email, "password": password, "totp_code": code},
            token=None,
        )
        minted = await client.request(
            "POST",
            "/v1/admin/me/tokens",
            json={"permission": "read"},
            token=str(login["token"]),
            idempotency_key=str(uuid4()),
        )
    return str(minted["token"])


async def token_command(
    args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None = None
) -> int:
    """Writes an operator token into the environment's file without printing
    it: the operator's, minted after a sign-in with the second factor, or the
    provisioner's, copied from the secret the grant job wrote."""
    env = load_environment(args.env)
    file = ops_file(env.name)
    if args.identity == "operator":
        if not sys.stdin.isatty():
            print(
                "the operator's token is minted in a person's own terminal: it asks for the "
                "password and the TOTP code there, and no agent holds either",
                file=sys.stderr,
            )
            return USAGE
        token = await mint_operator_token(env, transport)
        key = "TADAS_OPERATOR_TOKEN"
    else:
        if env.name not in CLOUD_ENVIRONMENTS:
            print(
                "the local provisioner token is set in the local env file or the process "
                "environment as TADAS_PROVISIONER_TOKEN",
                file=sys.stderr,
            )
            return USAGE
        token = await read_provisioner_token(env, args.profile)
        key = "TADAS_PROVISIONER_TOKEN"
    write_value(file, key, token)
    print(f"wrote {key} into {file}; it expires within the hour")
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

    p_token = sub.add_parser("token", help="write an operator token into the env file")
    p_token.add_argument("--env", required=True)
    p_token.add_argument("--identity", required=True, choices=["operator", "provisioner"])
    p_token.add_argument(
        "--profile",
        help="provisioner only: the person's own AWS profile that reads the secret; "
        "the environment's sign-in profile when absent (production's needs tadas-prod-power)",
    )
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
        if args.command == "token":
            return asyncio.run(token_command(args))
        return asyncio.run(size_command(args))
    except (ValueError, FileNotFoundError) as error:
        print(f"tadas-ops: {error}", file=sys.stderr)
        return USAGE


if __name__ == "__main__":
    sys.exit(main())
