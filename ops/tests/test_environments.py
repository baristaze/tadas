"""An environment from its file, the compose knobs under it for local, and
the process environment over both."""

import json
from pathlib import Path

import pytest

from tadas.ops.environments import (
    CLOUD_REGION,
    LOCAL_API_URL,
    LOCAL_ERROR_TRACKER_TOKEN,
    load_environment,
    parse_env_file,
)

REPOSITORY = Path(__file__).resolve().parents[2]


def test_env_lines_are_parsed_like_a_dotenv() -> None:
    values = parse_env_file(
        "# comment\nTADAS_API_URL=https://api.example.test/  # trailing\n"
        "export TADAS_OPERATOR_EMAIL=\"ops@example.test\"\nSEED_PASSWORD='p w'\nBROKEN\n"
    )
    assert values == {
        "TADAS_API_URL": "https://api.example.test/",
        "TADAS_OPERATOR_EMAIL": "ops@example.test",
        "SEED_PASSWORD": "p w",
    }


def test_local_with_no_file_reads_the_checkout_and_the_fixed_addresses(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env.example").write_text(
        "SEED_SLUG=acme\nSEED_EMAIL=owner@example.test\nSEED_PASSWORD=x\n"
    )
    (root / ".env").write_text("SEED_EMAIL=me@example.test\n")
    env = load_environment("local", home=tmp_path, root=root, process_env={})
    assert env.api_url == LOCAL_API_URL
    assert env.seed is not None and env.seed.owner_email == "me@example.test"
    assert env.seed.slug == "acme" and env.seed.password == "x"
    assert env.error_tracker_token == LOCAL_ERROR_TRACKER_TOKEN
    assert env.prometheus_url and env.jaeger_url and not env.is_cloud
    assert env.operator_email is None


def test_a_cloud_environment_needs_its_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="staging"):
        load_environment("staging", home=tmp_path, root=tmp_path, process_env={})


def test_a_cloud_file_names_everything_and_the_process_env_overrides(tmp_path: Path) -> None:
    file = tmp_path / ".config" / "tadas" / "ops" / "staging.env"
    file.parent.mkdir(parents=True)
    file.write_text(
        "TADAS_API_URL=https://api.staging.example.test\n"
        "TADAS_OPERATOR_EMAIL=ops@example.test\nTADAS_OPERATOR_PASSWORD=secret\n"
        "TADAS_ERROR_TRACKER_URL=https://sentry.io\nTADAS_ERROR_TRACKER_TOKEN=tok\n"
        "TADAS_ERROR_TRACKER_ORG=acme\n"
    )
    env = load_environment(
        "staging", home=tmp_path, root=tmp_path, process_env={"TADAS_AWS_REGION": "eu-west-1"}
    )
    assert env.is_cloud and env.api_url == "https://api.staging.example.test"
    assert env.aws_profile == "tadas-staging-investigate" and env.aws_region == "eu-west-1"
    assert env.error_tracker_org == "acme" and env.seed is None
    assert env.prometheus_url is None and env.jaeger_url is None


def test_the_cloud_region_is_the_one_the_environments_name() -> None:
    layout = json.loads((REPOSITORY / "deployment" / "cloud" / "environments.json").read_text())
    assert CLOUD_REGION == layout["region"]


@pytest.mark.parametrize("name", ["prod", "dev", "Staging"])
def test_an_unknown_environment_is_refused_rather_than_run_locally(
    tmp_path: Path, name: str
) -> None:
    with pytest.raises(ValueError, match="is not one of local, production, staging"):
        load_environment(name, home=tmp_path, root=tmp_path, process_env={})
