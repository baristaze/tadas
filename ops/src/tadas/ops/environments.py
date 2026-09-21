"""One named environment: where the API is, who the operator is (a read
entry on the allowlist, what every read runs as) and who the provisioner is
(a write entry, used only to create the tenants a traffic run needs), and
where its signals are read back from. `staging` and `production` are read from an
owner-only file outside the repository, `~/.config/tadas/ops/<env>.env`;
`local` reads the same file when it exists and otherwise the compose stack's
own knobs (`.env.example`, then `.env`) from the repository root, so the local
stack is an environment with nothing to set up. The process environment
overrides either file, key by key."""

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

LOCAL_API_URL = "http://127.0.0.1:8000"
LOCAL_PROMETHEUS_URL = "http://localhost:59090"
LOCAL_JAEGER_URL = "http://localhost:56686"
LOCAL_ERROR_TRACKER_URL = "http://localhost:58000"
LOCAL_ERROR_TRACKER_TOKEN = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
"""The read-only API token `deployment/local/glitchtip/seed.py` creates, fixed
the way the project key is, so the local reader needs no click through the UI."""

KEYS = (
    "TADAS_API_URL",
    "TADAS_OPERATOR_EMAIL",
    "TADAS_OPERATOR_PASSWORD",
    "TADAS_PROVISIONER_EMAIL",
    "TADAS_PROVISIONER_PASSWORD",
    "TADAS_ERROR_TRACKER_URL",
    "TADAS_ERROR_TRACKER_TOKEN",
    "TADAS_ERROR_TRACKER_ORG",
    "TADAS_ERROR_TRACKER_PROJECT",
    "TADAS_PROMETHEUS_URL",
    "TADAS_JAEGER_URL",
    "TADAS_AWS_PROFILE",
    "TADAS_AWS_REGION",
    "SEED_SLUG",
    "SEED_EMAIL",
    "SEED_MEMBER_EMAIL",
    "SEED_PASSWORD",
)
"""Every key an environment file may set; anything else in it is ignored."""

CLOUD_ENVIRONMENTS = frozenset({"staging", "production"})


@dataclass(frozen=True)
class SeedPeople:
    """The org and the two people `make seed` creates, which a local run with
    `--orgs 0` drives instead of provisioning tenants of its own."""

    slug: str
    owner_email: str
    member_email: str
    password: str


@dataclass(frozen=True)
class Environment:
    name: str
    api_url: str
    operator_email: str | None
    operator_password: str | None
    provisioner_email: str | None
    provisioner_password: str | None
    error_tracker_url: str | None
    error_tracker_token: str | None
    error_tracker_org: str
    error_tracker_project: str
    prometheus_url: str | None
    jaeger_url: str | None
    aws_profile: str | None
    aws_region: str | None
    seed: SeedPeople | None

    @property
    def is_cloud(self) -> bool:
        return self.name in CLOUD_ENVIRONMENTS


def parse_env_file(text: str) -> dict[str, str]:
    """`KEY=value` lines; blank lines and `#` comments skipped, an `export `
    prefix and matching quotes dropped. The same shape `.env.example` has."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key.strip()] = value
    return values


def ops_file(name: str, home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "tadas" / "ops" / f"{name}.env"


def repository_root(start: Path | None = None) -> Path | None:
    """The checkout `local` reads the compose knobs from: the nearest ancestor
    of the working directory with an `.env.example`, or git's answer."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".env.example").is_file():
            return candidate
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except OSError, subprocess.CalledProcessError:
        return None
    return Path(top) if top and (Path(top) / ".env.example").is_file() else None


def environment_of(name: str, values: Mapping[str, str]) -> Environment:
    """An environment from resolved values. `local` fills what the file left
    out with the compose stack's addresses; a cloud environment leaves it out."""
    local = name not in CLOUD_ENVIRONMENTS

    def get(key: str, default: str | None = None) -> str | None:
        value = values.get(key)
        return value if value else default

    seed: SeedPeople | None = None
    if values.get("SEED_EMAIL") or local:
        seed = SeedPeople(
            slug=get("SEED_SLUG", "acme") or "acme",
            owner_email=get("SEED_EMAIL", "owner@example.test") or "owner@example.test",
            member_email=get("SEED_MEMBER_EMAIL", "bob@example.test") or "bob@example.test",
            password=get("SEED_PASSWORD", "tadas-local") or "tadas-local",
        )
    api_url = get("TADAS_API_URL", LOCAL_API_URL if local else None)
    if not api_url:
        raise ValueError(f"environment {name!r} names no TADAS_API_URL")
    return Environment(
        name=name,
        api_url=api_url.rstrip("/"),
        operator_email=get("TADAS_OPERATOR_EMAIL"),
        operator_password=get("TADAS_OPERATOR_PASSWORD"),
        provisioner_email=get("TADAS_PROVISIONER_EMAIL"),
        provisioner_password=get("TADAS_PROVISIONER_PASSWORD"),
        error_tracker_url=get(
            "TADAS_ERROR_TRACKER_URL", LOCAL_ERROR_TRACKER_URL if local else None
        ),
        error_tracker_token=get(
            "TADAS_ERROR_TRACKER_TOKEN", LOCAL_ERROR_TRACKER_TOKEN if local else None
        ),
        error_tracker_org=get("TADAS_ERROR_TRACKER_ORG", "tadas") or "tadas",
        error_tracker_project=get("TADAS_ERROR_TRACKER_PROJECT", "tadas") or "tadas",
        prometheus_url=get("TADAS_PROMETHEUS_URL", LOCAL_PROMETHEUS_URL if local else None),
        jaeger_url=get("TADAS_JAEGER_URL", LOCAL_JAEGER_URL if local else None),
        aws_profile=get("TADAS_AWS_PROFILE", None if local else f"tadas-{name}-investigate"),
        aws_region=get("TADAS_AWS_REGION", None if local else "us-east-1"),
        seed=seed,
    )


def load_environment(
    name: str,
    *,
    path: Path | None = None,
    home: Path | None = None,
    root: Path | None = None,
    process_env: Mapping[str, str] | None = None,
) -> Environment:
    """The file for `name` (or `path`), the repository's compose knobs under
    it for `local`, and the process environment over both. A cloud environment
    with no file is an error: its addresses and its operator are secrets that
    live nowhere else."""
    if name != "local" and name not in CLOUD_ENVIRONMENTS:
        # A typo (`prod`) or an environment this tool has no reader for
        # (`dev`) would otherwise run against the local stack unannounced.
        known = ", ".join(sorted({"local", *CLOUD_ENVIRONMENTS}))
        raise ValueError(f"environment {name!r} is not one of {known}")
    values: dict[str, str] = {}
    local = name not in CLOUD_ENVIRONMENTS
    if local:
        checkout = root or repository_root()
        if checkout is not None:
            for candidate in (checkout / ".env.example", checkout / ".env"):
                if candidate.is_file():
                    values.update(parse_env_file(candidate.read_text()))
    file = path or ops_file(name, home)
    if file.is_file():
        values.update(parse_env_file(file.read_text()))
    elif not local:
        raise FileNotFoundError(f"no environment file for {name!r} at {file}")
    env = os.environ if process_env is None else process_env
    for key in KEYS:
        if env.get(key):
            values[key] = env[key]
    return environment_of(name, {k: v for k, v in values.items() if k in KEYS})
