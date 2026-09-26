"""Where a deploy's minutes went, from what the pipeline and the cluster
already record.

    gh run view <run id> --json createdAt,updatedAt,jobs > run.json
    uv run python ops/audit/deploy_timeline.py steps run.json [--at-least 5]

    aws ecs describe-services --cluster tadas-<env> --services api maintenance \\
      --profile tadas-<env>-investigate > services.json
    uv run python ops/audit/deploy_timeline.py events services.json \
      --since <ISO time> --until <ISO time>

`steps` prints every job of the run with its start (as minutes and seconds
after the run was created) and its length, then every step at least
`--at-least` seconds long, longest first, so the few steps that hold the
minutes stand out. `events` prints the ECS service events inside the window,
oldest first, each with its offset from `--since`: a task started, registered
with its target group, failed its health checks, drained, and the service
reaching a steady state. Neither calls anything; each reads a file.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def clock(seconds: float) -> str:
    whole = round(seconds)
    return f"{whole // 60}m{whole % 60:02d}s"


def steps(run: dict[str, Any], at_least: float) -> list[str]:
    """The run's jobs in the order they started, then its long steps."""
    start = when(run["createdAt"])
    jobs = [j for j in run["jobs"] if j.get("startedAt") and j.get("completedAt")]
    jobs.sort(key=lambda j: j["startedAt"])
    end = max((when(j["completedAt"]) for j in jobs), default=start)
    lines = [f"run: {clock((end - start).total_seconds())} from creation to its last job's end", ""]
    lines += ["| Job | Starts at | Takes |", "|---|---|---|"]
    for job in jobs:
        began, ended = when(job["startedAt"]), when(job["completedAt"])
        at, length = (began - start).total_seconds(), (ended - began).total_seconds()
        lines.append(f"| {job['name']} | +{clock(at)} | {clock(length)} |")
    long: list[tuple[float, str, str]] = []
    for job in jobs:
        for step in job.get("steps", []):
            if not step.get("startedAt") or not step.get("completedAt"):
                continue
            length = (when(step["completedAt"]) - when(step["startedAt"])).total_seconds()
            if length >= at_least:
                long.append((length, job["name"], step["name"]))
    lines += ["", f"| Step (at least {clock(at_least)}) | Job | Takes |", "|---|---|---|"]
    for length, job_name, step_name in sorted(long, reverse=True):
        lines.append(f"| {step_name} | {job_name} | {clock(length)} |")
    return lines


def events(services: dict[str, Any], since: datetime, until: datetime) -> list[str]:
    """Every service event inside the window, oldest first."""
    found: list[tuple[datetime, str, str]] = []
    for service in services.get("services", []):
        for event in service.get("events", []):
            at = (
                when(event["createdAt"])
                if isinstance(event["createdAt"], str)
                else event["createdAt"]
            )
            if since <= at <= until:
                found.append((at, service["serviceName"], event["message"]))
    found.sort()
    lines = ["| At | Service | Event |", "|---|---|---|"]
    for at, service_name, message in found:
        lines.append(f"| +{clock((at - since).total_seconds())} | {service_name} | {message} |")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deploy_timeline", description=(__doc__ or "").split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("steps", help="a run's jobs and its long steps, from gh run view --json")
    s.add_argument("file", type=Path)
    s.add_argument(
        "--at-least", type=float, default=5.0, help="seconds; shorter steps are left out"
    )
    e = sub.add_parser("events", help="the ECS service events of a window, from describe-services")
    e.add_argument("file", type=Path)
    e.add_argument("--since", required=True, help="ISO 8601, with its zone")
    e.add_argument("--until", required=True, help="ISO 8601, with its zone")
    args = parser.parse_args(argv)
    data = json.loads(args.file.read_text())
    if args.command == "steps":
        print("\n".join(steps(data, args.at_least)))
    else:
        print("\n".join(events(data, when(args.since), when(args.until))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
