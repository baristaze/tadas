"""The administrator's two scripts, dry-run and refused.

No cloud is needed: a dry run prints every command instead of running it,
and a refusal happens before any command. HOME is a temporary directory so a
dry run that wrote a profile or an env file by mistake would be caught.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CREATE = ROOT / "scripts" / "cloud_create.sh"
NUKE = ROOT / "scripts" / "cloud_nuke.sh"

INPUTS = {
    "AWS_PROFILE": "tadas-admin",
    "DNS_ZONE_NAME": "tadas.example",
    "OWNER_EMAIL": "owner@tadas.example",
    "ALARM_EMAIL": "alarms@tadas.example",
    "TF_STATE_BUCKET": "tadas-state-test",
}


def _run(
    script: Path, *args: str, home: Path, **overrides: str | None
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "HOME": str(home), **INPUTS}
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        ["bash", str(script), *args], capture_output=True, text=True, env=env, cwd=ROOT
    )


def test_create_staging_dry_run_prints_every_step_and_writes_nothing(tmp_path: Path) -> None:
    result = _run(CREATE, "staging", "--dry-run", home=tmp_path)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "+ aws sts get-caller-identity --profile tadas-admin" in out
    assert "+ gh auth status" in out
    assert "+ terraform -chdir=deployment/terraform/shared apply -input=false" in out
    assert "-var owner_email=owner@tadas.example" in out
    assert "init -input=false -migrate-state -force-copy" in out
    assert "-backend-config=bucket=tadas-state-test" in out
    assert "+ aws iam create-access-key --user-name <operators_user_name>" in out
    assert "aws_secret_access_key = ****" in out
    assert "<secret access key>" not in out
    assert "[profile tadas-staging-investigate]" in out
    assert "role_arn = <staging_investigate_role_arn>" in out
    assert "[profile tadas-production-investigate]" in out
    assert "source_profile = tadas-operators" in out
    assert "+ gh variable set AWS_STAGING_ROLE_ARN --body <staging_deploy_role_arn>" in out
    assert "+ gh variable set ALARM_EMAIL --body alarms@tadas.example" in out
    assert "+ gh api -X PUT repos/{owner}/{repo}/environments/production-plan" in out
    assert "environments/production -f reviewers[][type]=User -F reviewers[][id]=<owner id>" in out
    assert "TADAS_API_URL=https://api.staging.tadas.example" in out
    assert "+ gh workflow run deploy-staging.yml --ref main" in out
    assert "uv run tadas-ops signals check --env staging" in out
    assert not (tmp_path / ".aws").exists()
    assert not (tmp_path / ".config").exists()
    assert not (ROOT / "deployment/terraform/shared/backend_override.tf").exists()


def test_create_production_dry_run_releases_instead_of_deploying(tmp_path: Path) -> None:
    result = _run(CREATE, "production", "--dry-run", home=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "+ gh workflow run release.yml --ref main" in result.stdout
    assert "TADAS_API_URL=https://api.tadas.example" in result.stdout
    assert "uv run tadas-ops signals check --env production" in result.stdout


@pytest.mark.parametrize("script", [CREATE, NUKE], ids=["create", "nuke"])
def test_refuses_any_profile_but_the_administrator(script: Path, tmp_path: Path) -> None:
    result = _run(script, "staging", "--dry-run", home=tmp_path, AWS_PROFILE="default")
    assert result.returncode == 2
    assert "refused" in result.stderr
    assert "tadas-admin" in result.stderr
    assert result.stdout == ""


def test_create_refuses_a_missing_input_by_name(tmp_path: Path) -> None:
    result = _run(CREATE, "staging", "--dry-run", home=tmp_path, OWNER_EMAIL=None)
    assert result.returncode == 2
    assert "refused: missing: OWNER_EMAIL" in result.stderr


def test_create_takes_the_inputs_as_flags_too(tmp_path: Path) -> None:
    result = _run(
        CREATE,
        "staging",
        "--dry-run",
        "--owner-email",
        "flag@tadas.example",
        home=tmp_path,
        OWNER_EMAIL=None,
    )
    assert result.returncode == 0, result.stderr
    assert "-var owner_email=flag@tadas.example" in result.stdout


def test_nuke_staging_dry_run_lifts_the_protections_then_destroys(tmp_path: Path) -> None:
    result = _run(NUKE, "staging", "--dry-run", home=tmp_path)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "+ terraform -chdir=deployment/terraform/environments/staging init" in out
    apply = out.index("+ terraform -chdir=deployment/terraform/environments/staging apply")
    destroy = out.index("+ terraform -chdir=deployment/terraform/environments/staging destroy")
    assert apply < destroy
    assert out.count("-var destroyable=true") == 2
    assert "-var api_domain_name=api.staging.tadas.example" in out
    assert "== 5. What remains" in out
    assert "the hosted zone tadas.example" in out
    assert "the state prefix environments/staging/" in out


def test_nuke_refuses_production_without_its_typed_name(tmp_path: Path) -> None:
    result = _run(NUKE, "production", "--dry-run", home=tmp_path)
    assert result.returncode == 2
    assert "--confirm production" in result.stderr
    assert result.stdout == ""


def test_nuke_refuses_production_while_main_still_protects_the_database(tmp_path: Path) -> None:
    # On origin/main the production root reads database_deletion_protection =
    # true, so the typed name alone is not enough. A checkout without
    # origin/main refuses too, on the reading.
    result = _run(NUKE, "production", "--confirm", "production", "--dry-run", home=tmp_path)
    assert result.returncode == 2
    assert "refused" in result.stderr
    assert "origin/main" in result.stderr
    assert result.stdout == ""
