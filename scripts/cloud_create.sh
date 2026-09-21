#!/usr/bin/env bash
# Create an environment from nothing to its first deploy, as the
# administrator. The `ops-cloud-deployment-create` skill narrates this script;
# the script is the hands.
#
#   scripts/cloud_create.sh staging [--dry-run]
#   scripts/cloud_create.sh production [--dry-run]
#
# What it does, in order: verifies it holds the administrator profile and a
# GitHub login; applies `deployment/terraform/shared` with local state and
# moves that state into the bucket it made; mints an access key for the
# `tadas-operators` user and writes the profiles into ~/.aws (never over an
# existing one); sets the repository variables from the shared outputs;
# creates the three GitHub environments; writes the operator's env file for
# the environment; and starts the first deploy through the pipeline, which is
# how every other commit reaches the cloud. It prints every command before it
# runs it, and `--dry-run` prints them without running anything.
#
# Inputs, as flags or as environment variables:
#   --profile        AWS_PROFILE       the administrator profile, tadas-admin
#   --dns-zone-name  DNS_ZONE_NAME     the hosted zone, e.g. tadas.fyi
#   --owner-email    OWNER_EMAIL       where the budget and anomaly mail goes
#   --alarm-email    ALARM_EMAIL       where the environment's alarms go
#   --state-bucket   TF_STATE_BUCKET   the state bucket every root shares
#   --region         AWS_REGION        default us-east-1
set -euo pipefail

usage() {
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

refuse() {
  echo "refused: $*" >&2
  exit 2
}

environment=""
dry_run=false
profile="${AWS_PROFILE:-}"
dns_zone_name="${DNS_ZONE_NAME:-}"
owner_email="${OWNER_EMAIL:-}"
alarm_email="${ALARM_EMAIL:-}"
state_bucket="${TF_STATE_BUCKET:-}"
region="${AWS_REGION:-us-east-1}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=true ;;
    --profile) profile="${2:-}"; shift ;;
    --dns-zone-name) dns_zone_name="${2:-}"; shift ;;
    --owner-email) owner_email="${2:-}"; shift ;;
    --alarm-email) alarm_email="${2:-}"; shift ;;
    --state-bucket) state_bucket="${2:-}"; shift ;;
    --region) region="${2:-}"; shift ;;
    -h|--help) usage ;;
    -*) echo "unknown flag: $1" >&2; usage ;;
    *) [ -z "$environment" ] || usage; environment="$1" ;;
  esac
  shift
done

case "$environment" in
  staging) root="environments/staging" ;;
  production) root="environments/prod" ;;
  "") usage ;;
  *) refuse "the environment is staging or production, not '$environment'" ;;
esac

# The credential is the boundary. This script creates roles and mints a key,
# so it runs under the administrator profile and refuses any other: a wider
# one does not exist, and a narrower one cannot do this.
[ "$profile" = "tadas-admin" ] || refuse "this runs under the tadas-admin profile only (AWS_PROFILE or --profile); it holds '${profile:-nothing}'"

missing=""
[ -n "$dns_zone_name" ] || missing="$missing DNS_ZONE_NAME"
[ -n "$owner_email" ] || missing="$missing OWNER_EMAIL"
[ -n "$alarm_email" ] || missing="$missing ALARM_EMAIL"
[ -n "$state_bucket" ] || missing="$missing TF_STATE_BUCKET"
[ -z "$missing" ] || refuse "missing:$missing (as flags or environment variables)"

cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
export AWS_PROFILE="$profile"

# Every command is printed before it runs; a dry run stops at the printing.
run() {
  printf '+ %s\n' "$*"
  if ! $dry_run; then "$@"; fi
}

say() {
  printf '%s\n' "$*"
}

# A value a later command needs: in a dry run, a placeholder that names it.
output_of() {
  if $dry_run; then
    echo "<$1>"
  else
    terraform -chdir=deployment/terraform/shared output -raw "$1"
  fi
}

# owner/name, from the origin remote (ssh or https) unless GITHUB_REPOSITORY
# says otherwise; the shared root's roles trust this repository's jobs.
repository="${GITHUB_REPOSITORY:-}"
if [ -z "$repository" ]; then
  origin="$(git remote get-url origin 2>/dev/null || true)"
  origin="${origin%.git}"
  origin="${origin%/}"
  name="${origin##*/}"
  owner="${origin%/*}"
  owner="${owner##*[:/]}"
  if [ -n "$name" ] && [ -n "$owner" ]; then repository="$owner/$name"; fi
fi
repository="${repository:-<owner>/<name>}"

case "$environment" in
  staging) api_url="https://api.staging.$dns_zone_name" ;;
  production) api_url="https://api.$dns_zone_name" ;;
esac

say "== 1. Who am I"
run aws sts get-caller-identity --profile "$profile"
run gh auth status

say "== 2. The shared root: roles, boundaries, the operators user, the budget, the zone"
shared=deployment/terraform/shared
backend_args=(
  -backend-config="bucket=$state_bucket"
  -backend-config="key=shared/terraform.tfstate"
  -backend-config="region=$region"
  -backend-config="use_lockfile=true"
)
shared_vars=(
  -var "github_repository=$repository"
  -var "state_bucket=$state_bucket"
  -var "dns_zone_name=$dns_zone_name"
  -var "owner_email=$owner_email"
  -var "region=$region"
)
if $dry_run || ! aws s3api head-bucket --bucket "$state_bucket" >/dev/null 2>&1; then
  # The bucket the state lives in is made by this root, so the first apply
  # holds its state locally, and the state moves into the bucket after.
  say "The state bucket does not exist yet: shared applies with local state, then its state moves into the bucket."
  say "+ write $shared/backend_override.tf (terraform { backend \"local\" {} })"
  if ! $dry_run; then
    printf 'terraform {\n  backend "local" {}\n}\n' > "$shared/backend_override.tf"
    trap 'rm -f "$shared/backend_override.tf"' EXIT
  fi
  run terraform -chdir="$shared" init -input=false
  run terraform -chdir="$shared" apply -input=false "${shared_vars[@]}"
  say "+ rm $shared/backend_override.tf"
  if ! $dry_run; then rm -f "$shared/backend_override.tf"; trap - EXIT; fi
  run terraform -chdir="$shared" init -input=false -migrate-state -force-copy "${backend_args[@]}"
  say "+ rm -f $shared/terraform.tfstate $shared/terraform.tfstate.backup"
  if ! $dry_run; then rm -f "$shared/terraform.tfstate" "$shared/terraform.tfstate.backup"; fi
  say "The zone's name servers go to the registrar, once:"
  run terraform -chdir="$shared" output -json dns_name_servers
else
  run terraform -chdir="$shared" init -input=false "${backend_args[@]}"
  run terraform -chdir="$shared" apply -input=false "${shared_vars[@]}"
fi

say "== 3. The operators' key and the profiles"
aws_dir="$HOME/.aws"
credentials="$aws_dir/credentials"
config="$aws_dir/config"
operators_user="$(output_of operators_user_name)"
staging_role="$(output_of staging_investigate_role_arn)"
production_role="$(output_of production_investigate_role_arn)"

has_profile() {
  [ -f "$1" ] && grep -qxF "[$2]" "$1"
}

if has_profile "$credentials" "tadas-operators"; then
  say "$credentials already has [tadas-operators]; the key is not minted again."
else
  # The key is minted here and lands in the person's home and nowhere else:
  # not in Terraform's state, not in this script's output. Printed by hand,
  # not through `run`, because its output is the secret.
  say "+ aws iam create-access-key --user-name $operators_user --profile $profile --output json"
  if $dry_run; then
    access_key_id="<access key id>"
    secret_access_key="<secret access key>"
  else
    key_json="$(aws iam create-access-key --user-name "$operators_user" --profile "$profile" --output json)"
    access_key_id="$(printf '%s' "$key_json" | jq -r .AccessKey.AccessKeyId)"
    secret_access_key="$(printf '%s' "$key_json" | jq -r .AccessKey.SecretAccessKey)"
  fi
  say "+ append to $credentials:"
  say "  [tadas-operators]"
  say "  aws_access_key_id = $access_key_id"
  say "  aws_secret_access_key = ****"
  if ! $dry_run; then
    mkdir -p "$aws_dir"
    (umask 077; printf '\n[tadas-operators]\naws_access_key_id = %s\naws_secret_access_key = %s\n' "$access_key_id" "$secret_access_key" >> "$credentials")
  fi
fi

append_config() {
  # $1 profile name, then the lines under its header.
  local name="$1"
  shift
  if has_profile "$config" "profile $name"; then
    say "$config already has [profile $name]; it is left as it is."
    return
  fi
  say "+ append to $config:"
  say "  [profile $name]"
  local line
  for line in "$@"; do say "  $line"; done
  if ! $dry_run; then
    mkdir -p "$aws_dir"
    {
      printf '\n[profile %s]\n' "$name"
      for line in "$@"; do printf '%s\n' "$line"; done
    } >> "$config"
  fi
}

has_profile "$config" "profile tadas-admin" || say "note: $config has no [profile tadas-admin]; the administrator profile is yours to keep, this script only reads it."
append_config tadas-operators "region = $region"
append_config tadas-staging-investigate "role_arn = $staging_role" "source_profile = tadas-operators" "region = $region"
append_config tadas-production-investigate "role_arn = $production_role" "source_profile = tadas-operators" "region = $region"

say "== 4. The repository variables, from the shared outputs"
# Read into variables first: a substitution inside an argument does not stop
# the run under `set -e`, and a failed read would set the variable empty.
staging_deploy_role="$(output_of staging_deploy_role_arn)"
production_plan_role="$(output_of production_plan_role_arn)"
production_deploy_role="$(output_of production_deploy_role_arn)"
run gh variable set AWS_STAGING_ROLE_ARN --body "$staging_deploy_role"
run gh variable set AWS_PRODUCTION_PLAN_ROLE_ARN --body "$production_plan_role"
run gh variable set AWS_PRODUCTION_ROLE_ARN --body "$production_deploy_role"
run gh variable set TF_STATE_BUCKET --body "$state_bucket"
run gh variable set DNS_ZONE_NAME --body "$dns_zone_name"
run gh variable set ALARM_EMAIL --body "$alarm_email"

say "== 5. The GitHub environments"
# `staging` and `production-plan` carry no rule: a reviewer on the plan
# would hold the plan the reviewer is meant to read. `production` requires
# the owner, and that reviewer is what gates the deploy credential.
run gh api -X PUT 'repos/{owner}/{repo}/environments/staging'
run gh api -X PUT 'repos/{owner}/{repo}/environments/production-plan'
if $dry_run; then
  owner_id="<owner id>"
else
  owner_id="$(gh api 'repos/{owner}/{repo}' -q .owner.id)"
fi
run gh api -X PUT 'repos/{owner}/{repo}/environments/production' -f 'reviewers[][type]=User' -F "reviewers[][id]=$owner_id"

say "== 6. The operator's env file for $environment"
ops_dir="$HOME/.config/tadas/ops"
ops_file="$ops_dir/$environment.env"
if [ -f "$ops_file" ]; then
  say "$ops_file exists; it is left as it is."
else
  say "+ write $ops_file (mode 600):"
  say "  TADAS_API_URL=$api_url"
  say "  TADAS_OPERATOR_EMAIL=         # a read entry on the operator allowlist"
  say "  TADAS_OPERATOR_PASSWORD="
  say "  TADAS_PROVISIONER_EMAIL=      # a write entry; only the traffic generator uses it"
  say "  TADAS_PROVISIONER_PASSWORD="
  say "  TADAS_ERROR_TRACKER_URL="
  say "  TADAS_ERROR_TRACKER_TOKEN="
  if ! $dry_run; then
    mkdir -p "$ops_dir"
    (umask 077; printf 'TADAS_API_URL=%s\nTADAS_OPERATOR_EMAIL=\nTADAS_OPERATOR_PASSWORD=\nTADAS_PROVISIONER_EMAIL=\nTADAS_PROVISIONER_PASSWORD=\nTADAS_ERROR_TRACKER_URL=\nTADAS_ERROR_TRACKER_TOKEN=\n' "$api_url" > "$ops_file")
    chmod 600 "$ops_file"
  fi
fi

say "== 7. The first deploy, through the pipeline like every other"
case "$environment" in
  staging) run gh workflow run deploy-staging.yml --ref main ;;
  production) run gh workflow run release.yml --ref main ;;
esac

say "== 8. When the deploy is green, the smoke test: one request, then its signals by request id"
say "id=\$(curl -s -o /dev/null -D - $api_url/v1/me | awk 'tolower(\$1) == \"x-request-id:\" { print \$2 }' | tr -d '\\r')"
say "uv run tadas-ops signals check --env $environment --request-id \"\$id\""
say "The environment root is deployment/terraform/$root; the operator's file is $ops_file."
