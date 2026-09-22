"""The administrator's two scripts, dry-run and refused.

No cloud is needed: a dry run prints every command instead of running it,
and a refusal happens before any command. HOME is a temporary directory so a
dry run that wrote a profile or an env file by mistake would be caught.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CREATE = ROOT / "scripts" / "cloud_create.sh"
NUKE = ROOT / "scripts" / "cloud_nuke.sh"

INPUTS = {
    "OWNER_EMAIL": "owner@tadas.example",
    "ALARM_EMAIL": "alarms@tadas.example",
}
ENVIRONMENTS = json.loads((ROOT / "deployment" / "cloud" / "environments.json").read_text())
STAGING = ENVIRONMENTS["environments"]["staging"]
PRODUCTION = ENVIRONMENTS["environments"]["production"]


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
    account = STAGING["account_id"]
    expect = (
        f"+ aws sts get-caller-identity --profile tadas-staging-admin  (expect account {account})"
    )
    # Once before anything, once more right before the apply.
    assert out.count(expect) == 2
    assert "+ gh auth status" in out
    assert "+ terraform -chdir=deployment/terraform/bootstrap/staging apply -input=false" in out
    assert "-var owner_email=owner@tadas.example" in out
    assert "-var replicate_to_production=" in out
    assert "init -input=false -migrate-state -force-copy" in out
    assert f"-backend-config=bucket=tadas-state-{account}" in out
    assert "-backend-config=key=bootstrap/terraform.tfstate" in out
    assert f"-backend-config=region={ENVIRONMENTS['region']}" in out
    assert f"cloudflare GET /zones?name={ENVIRONMENTS['domain']}" in out
    assert f"NS {STAGING['api_domain_name']} -> " in out
    assert f"NS {STAGING['app_domain_name']} -> " in out
    assert "[profile tadas-staging-investigate]" in out
    assert "role_arn = <investigate_role_arn>" in out
    assert "source_profile = tadas-staging" in out
    assert "create-access-key" not in out
    assert "+ gh variable set AWS_ROLE_ARN --env staging --body <deploy_role_arn>" in out
    assert f"+ gh variable set TF_STATE_BUCKET --env staging --body tadas-state-{account}" in out
    assert "+ gh variable set ALARM_EMAIL --env staging --body alarms@tadas.example" in out
    assert "+ gh api -X PUT repos/{owner}/{repo}/environments/staging" in out
    assert "deployment_branch_policy[custom_branch_policies]=true" in out
    assert "environments/staging/deployment-branch-policies -f name=main -f type=branch" in out
    assert f"--env staging --body tadas-artifacts-{account}" in out
    assert "production-plan" not in out
    assert f"TADAS_API_URL=https://{STAGING['api_domain_name']}" in out
    assert "+ gh workflow run deploy-staging.yml --ref main" in out
    assert "uv run tadas-ops signals check --env staging" in out
    assert not (tmp_path / ".aws").exists()
    assert not (tmp_path / ".config").exists()
    assert not (ROOT / "deployment/terraform/bootstrap/staging/backend_override.tf").exists()


def test_create_production_dry_run_sets_two_environments_and_waits_for_replication(
    tmp_path: Path,
) -> None:
    result = _run(CREATE, "production", "--dry-run", home=tmp_path)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert f"(expect account {PRODUCTION['account_id']})" in out
    assert "+ terraform -chdir=deployment/terraform/bootstrap/prod apply -input=false" in out
    assert "replicate_to_production" not in out
    assert "+ gh variable set AWS_ROLE_ARN --env production-plan --body <plan_role_arn>" in out
    assert "+ gh variable set AWS_ROLE_ARN --env production --body <deploy_role_arn>" in out
    for github_environment in ["production-plan", "production"]:
        policy = f"environments/{github_environment}/deployment-branch-policies -f name=release"
        assert policy in out
    assert "tadas-artifacts-" in out
    assert "-f reviewers[][type]=User -F reviewers[][id]=<owner id>" in out
    assert "source_profile = tadas-prod" in out
    # The first release waits for a commit staging built after replication.
    assert "+ gh workflow run" not in out
    assert "scripts/cloud_create.sh staging, again" in out
    assert f"TADAS_API_URL=https://{PRODUCTION['api_domain_name']}" in out
    assert "uv run tadas-ops signals check --env production" in out


def test_create_refuses_to_run_for_real_without_the_cloudflare_token(tmp_path: Path) -> None:
    result = _run(CREATE, "staging", home=tmp_path, CLOUDFLARE_API_TOKEN=None)
    assert result.returncode == 2
    assert "refused: missing: CLOUDFLARE_API_TOKEN" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("script", [CREATE, NUKE], ids=["create", "nuke"])
def test_refuses_any_profile_but_the_environments_administrator(
    script: Path, tmp_path: Path
) -> None:
    # Production's administrator is the wrong account for staging.
    result = _run(
        script, "staging", "--dry-run", home=tmp_path, AWS_PROFILE=PRODUCTION["admin_profile"]
    )
    assert result.returncode == 2
    assert "refused" in result.stderr
    assert STAGING["admin_profile"] in result.stderr
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
    assert f"-var api_domain_name={STAGING['api_domain_name']}" in out
    assert "dns_zone_name" not in out
    assert out.count(f"(expect account {STAGING['account_id']})") == 3
    assert "== 5. What remains" in out
    assert "the bootstrap root, whole" in out
    assert "the state prefix environments/staging/" in out


def test_nuke_refuses_production_without_its_typed_name(tmp_path: Path) -> None:
    result = _run(NUKE, "production", "--dry-run", home=tmp_path)
    assert result.returncode == 2
    assert "--confirm production" in result.stderr
    assert result.stdout == ""


def test_nuke_refuses_production_while_release_still_protects_the_database(
    tmp_path: Path,
) -> None:
    # Production applies release, and there the root reads
    # database_deletion_protection = true, so the typed name alone is not
    # enough. A checkout without origin/release refuses too, on the reading.
    result = _run(NUKE, "production", "--confirm", "production", "--dry-run", home=tmp_path)
    assert result.returncode == 2
    assert "refused" in result.stderr
    assert "origin/release" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("workflow", ["deploy-staging.yml", "deploy-production.yml"])
def test_the_deploy_workflows_run_in_the_region_the_environments_name(workflow: str) -> None:
    text = (ROOT / ".github" / "workflows" / workflow).read_text()
    assert f"  AWS_REGION: {ENVIRONMENTS['region']}\n" in text


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_the_environment_roots_default_to_the_region_the_environments_name(
    environment: str,
) -> None:
    root = ENVIRONMENTS["environments"][environment]["environment_root"]
    text = (ROOT / "deployment" / "terraform" / root / "variables.tf").read_text()
    assert f'default     = "{ENVIRONMENTS["region"]}"' in text
