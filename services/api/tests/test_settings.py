"""Every knob of the API process is documented and wired: each field of
`ApiSettings` appears in `.env.example` under its prefix, and each field a
deployed process cannot leave at its local default is set in
`app_environment` or a secret of every Terraform environment. Both files are
read as text, the way a reviewer reads them. A field the cloud leaves at its
default is listed here with the reason, so a new field needs a decision."""

import re
import subprocess
from pathlib import Path

import pytest

from tadas.services.api.settings import ApiSettings

PREFIX = ApiSettings.model_config.get("env_prefix", "")

NOT_A_KNOB = {
    "secret_overrides": "the TADAS_SECRET_<ORG>_<NAME> family, documented by its example line",
}

LOCAL_DEFAULT_SERVES_THE_CLOUD = {
    # Until the Terraform environments inject the system login's URL secret;
    # the entry goes when they do.
    "database_system_url": "not yet wired: the system login's URL secret",
    "database_url_core": "one URL for every role until a role moves out",
    "database_url_activity": "one URL for every role until a role moves out",
    "database_url_queue": "one URL for every role until a role moves out",
    "database_url_admin": "one URL for every role until a role moves out",
    "database_pool_size": "the local default is the tuning",
    "database_pool_size_core": "one pool for every role until a role moves out",
    "database_pool_size_activity": "one pool for every role until a role moves out",
    "database_pool_size_queue": "one pool for every role until a role moves out",
    "database_pool_size_admin": "one pool for every role until a role moves out",
    "database_checkout_timeout_seconds": "the local default is the tuning",
    "database_checkout_timeout_seconds_core": "one pool for every role until a role moves out",
    "database_checkout_timeout_seconds_activity": "one pool for every role until a role moves out",
    "database_checkout_timeout_seconds_queue": "one pool for every role until a role moves out",
    "database_checkout_timeout_seconds_admin": "one pool for every role until a role moves out",
    "database_statement_timeout_seconds": "the local default is the tuning",
    "database_statement_timeout_seconds_core": "one pool for every role until a role moves out",
    "database_statement_timeout_seconds_activity": "one pool for every role until a role moves out",
    "database_statement_timeout_seconds_queue": "one pool for every role until a role moves out",
    "database_statement_timeout_seconds_admin": "one pool for every role until a role moves out",
    "buckets_root": "the local buckets backend only",
    "s3_endpoint_url": "the hosted endpoint; only MinIO needs one",
    "s3_access_key": "the task role signs; only MinIO needs a key",
    "s3_secret_key": "the task role signs; only MinIO needs a key",
    "sqs_endpoint_url": "the hosted endpoint; only ElasticMQ needs one",
    "secrets_file": "the local secrets backend only",
    "log_level": "INFO everywhere",
    "otel_endpoint": "traces go to the collector sidecar, wired in the task, not a knob",
    "aws_timeout_seconds": "the local default is the tuning",
    "valkey_timeout_seconds": "the local default is the tuning",
    "valkey_breaker_failures": "the local bound is the bound",
    "valkey_breaker_cooldown_seconds": "the local cool-down is the cool-down",
    "otel_timeout_seconds": "the local default is the tuning",
    "version": "the image carries it",
    "login_rate_limit": "the local budget is the budget",
    "login_rate_window_seconds": "the local window is the window",
    "sign_in_free_failures": "the local run is the run",
    "sign_in_delay_base_seconds": "the local delay is the delay",
    "sign_in_delay_cap_seconds": "the local cap is the cap",
    "login_lifetime_seconds": "the local lifetime is the lifetime",
    "session_lifetime_seconds": "the local lifetime is the lifetime",
    "session_idle_lifetime_seconds": "the local lifetime is the lifetime",
    "operator_token_max_lifetime_seconds": "an hour, the guideline's bound, everywhere",
    "totp_encryption_key": "the cloud package's secrets module injects it into the API alone",
    "signup_enabled": "open everywhere: a deployed environment has no other door",
    "signup_rate_limit": "the local budget is the budget",
    "signup_rate_window_seconds": "the local window is the window",
    "realtime_send_buffer_size": "the local size is the size",
    "realtime_control_buffer_size": "the local size is the size",
    "readiness_timeout_seconds": "shorter than every probe interval the deployment sets",
    "admission_limit_reads": "the local bound is the bound until a replica is measured",
    "admission_limit_writes": "the local bound is the bound until a replica is measured",
    "admission_retry_after_seconds": "the local wait is the wait",
}


def repository_root() -> Path:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).parent,
    ).stdout.strip()
    return Path(top)


def documented_knobs(env_example: str) -> set[str]:
    """The names on `NAME=` and `#NAME=` lines."""
    return set(re.findall(r"^#?([A-Z][A-Z0-9_]*)=", env_example, flags=re.MULTILINE))


def wired_knobs(terraform: str) -> set[str]:
    """The names given a value anywhere in the environment's graph: the
    shared `app_environment`, the process secrets, and a service's own block."""
    return set(re.findall(r"\b(TADAS_[A-Z0-9_]+)\s*=", terraform))


def graph(environment: Path) -> str:
    """The root and every module it calls: an environment root is thin, and
    the graph it applies lives in the module it names."""
    root = (environment / "main.tf").read_text()
    sources = re.findall(r'source\s*=\s*"([^"]+)"', root)
    return "\n".join(
        [root] + [(environment / source / "main.tf").read_text() for source in sources]
    )


def knobs() -> list[str]:
    return [
        f"{PREFIX}{field.upper()}" for field in ApiSettings.model_fields if field not in NOT_A_KNOB
    ]


def test_every_setting_is_in_env_example() -> None:
    documented = documented_knobs((repository_root() / ".env.example").read_text())
    missing = sorted(knob for knob in knobs() if knob not in documented)
    assert not missing, f"settings fields absent from .env.example: {missing}"


def environments() -> list[Path]:
    return sorted((repository_root() / "deployment" / "terraform" / "environments").iterdir())


@pytest.mark.parametrize("environment", environments(), ids=lambda path: path.name)
def test_every_setting_the_cloud_needs_is_wired(environment: Path) -> None:
    wired = wired_knobs(graph(environment))
    unwired = sorted(
        f"{PREFIX}{field.upper()}"
        for field in ApiSettings.model_fields
        if field not in NOT_A_KNOB
        and field not in LOCAL_DEFAULT_SERVES_THE_CLOUD
        and f"{PREFIX}{field.upper()}" not in wired
    )
    assert not unwired, f"{environment.name} sets no value for: {unwired}"
    fields = ApiSettings.model_fields
    stale = sorted(field for field in LOCAL_DEFAULT_SERVES_THE_CLOUD if field not in fields)
    assert not stale, f"exceptions naming no field: {stale}"
