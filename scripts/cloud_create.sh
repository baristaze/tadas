#!/usr/bin/env bash
# Create an environment's account from nothing to its first deploy, as the
# account's administrator. The `ops-cloud-deployment-create` skill narrates
# this script; the script is the hands.
#
#   scripts/cloud_create.sh staging [--dry-run]
#   scripts/cloud_create.sh production [--dry-run]
#
# Each environment has an AWS account of its own, and
# deployment/cloud/environments.json names it: the account id, the
# administrator profile that bootstraps it, the Identity Center profile an
# operator signs in with, the region, and the environment's two public
# names. This script reads everything from there and refuses to act in any
# other account.
#
# What it does, in order: checks the profile is the environment's
# administrator and the account is the environment's, and checks the GitHub
# login; applies the environment's bootstrap root with local state and moves
# that state into the bucket it made; delegates the two public names from
# the domain's zone at Cloudflare to the zones the root made; writes the
# investigate profile, chained from the Identity Center profile; creates the
# GitHub environments and sets their variables from the root's outputs;
# writes the operator's env file; and starts the first deploy through the
# pipeline, which is how every later commit reaches the cloud. It checks the
# account again before every apply. It prints every command before it runs
# it, and `--dry-run` prints them without running anything.
#
# Staging runs first, then production, then staging again: staging's images
# and portal builds replicate into production's account, and the replication
# needs production's bucket to exist. The second staging run finds it and
# turns the replication on.
#
# Inputs, as flags or as environment variables:
#   --owner-email    OWNER_EMAIL           where the budget and anomaly mail goes
#   --alarm-email    ALARM_EMAIL           where the environment's alarms go
#                    CLOUDFLARE_API_TOKEN  a token with DNS edit on the domain's
#                                          zone; an environment variable only,
#                                          so it never lands in shell history
set -euo pipefail

usage() {
  sed -n '2,38p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

refuse() {
  echo "refused: $*" >&2
  exit 2
}

environment=""
dry_run=false
profile="${AWS_PROFILE:-}"
owner_email="${OWNER_EMAIL:-}"
alarm_email="${ALARM_EMAIL:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=true ;;
    --profile) profile="${2:-}"; shift ;;
    --owner-email) owner_email="${2:-}"; shift ;;
    --alarm-email) alarm_email="${2:-}"; shift ;;
    -h|--help) usage ;;
    -*) echo "unknown flag: $1" >&2; usage ;;
    *) [ -z "$environment" ] || usage; environment="$1" ;;
  esac
  shift
done

case "$environment" in
  staging|production) ;;
  "") usage ;;
  *) refuse "the environment is staging or production, not '$environment'" ;;
esac

cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
environments=deployment/cloud/environments.json

config() {
  jq -er "$1" "$environments"
}

region="$(config .region)"
domain="$(config .domain)"
account_id="$(config ".environments.$environment.account_id")"
admin_profile="$(config ".environments.$environment.admin_profile")"
sso_profile="$(config ".environments.$environment.sso_profile")"
bootstrap_root="deployment/terraform/$(config ".environments.$environment.bootstrap_root")"
environment_root="deployment/terraform/$(config ".environments.$environment.environment_root")"
api_domain_name="$(config ".environments.$environment.api_domain_name")"
app_domain_name="$(config ".environments.$environment.app_domain_name")"
state_bucket="tadas-state-$account_id"

# The credential is the boundary. This script creates roles and trust, so it
# runs under the environment's administrator profile and refuses any other:
# a PowerUserAccess profile cannot write IAM, and another environment's
# administrator is the wrong account.
profile="${profile:-$admin_profile}"
[ "$profile" = "$admin_profile" ] || refuse "$environment is created under the $admin_profile profile only (AWS_PROFILE or --profile); it holds '$profile'"

missing=""
[ -n "$owner_email" ] || missing="$missing OWNER_EMAIL"
[ -n "$alarm_email" ] || missing="$missing ALARM_EMAIL"
if ! $dry_run && [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then missing="$missing CLOUDFLARE_API_TOKEN"; fi
[ -z "$missing" ] || refuse "missing:$missing (as flags or environment variables)"

# Keys exported in the shell outrank a profile for Terraform, and a region
# exported there outranks the one the environment names. Neither is allowed
# to decide where this lands.
exported=""
for name in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_PROFILE AWS_DEFAULT_REGION; do
  if [ -n "${!name:-}" ]; then exported="$exported $name"; fi
done
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_PROFILE AWS_DEFAULT_REGION
export AWS_PROFILE="$profile"
export AWS_REGION="$region"
if [ -n "$exported" ]; then
  echo "note: the shell exported$exported; cleared for this run. An exported key is a long-lived one, and this platform uses none."
fi

# Every command is printed before it runs; a dry run stops at the printing.
run() {
  printf '+ %s\n' "$*"
  if ! $dry_run; then "$@"; fi
}

say() {
  printf '%s\n' "$*"
}

# Before anything that writes: the profile resolves to the environment's
# account, or nothing runs. The providers pin the same account, so a check
# skipped here would still fail there.
check_account() {
  say "+ aws sts get-caller-identity --profile $profile  (expect account $account_id)"
  if $dry_run; then return; fi
  local actual
  actual="$(aws sts get-caller-identity --profile "$profile" --query Account --output text)"
  [ "$actual" = "$account_id" ] || refuse "$profile resolves to account $actual, and $environment is account $account_id"
}

# A value a later command needs: in a dry run, a placeholder that names it.
output_of() {
  if $dry_run; then
    echo "<$1>"
  else
    terraform -chdir="$bootstrap_root" output -raw "$1"
  fi
}

case "$environment" in
  staging) github_environments="staging" ;;
  production) github_environments="production-plan and production" ;;
esac

say "== 1. Who am I"
check_account
run gh auth status

say "== 2. The bootstrap root: state, registry, OIDC trust, the deploy roles, the investigate role, the budget, the zones"
backend_args=(
  -backend-config="bucket=$state_bucket"
  -backend-config="key=bootstrap/terraform.tfstate"
  -backend-config="region=$region"
  -backend-config="use_lockfile=true"
)
bootstrap_vars=(-var "owner_email=$owner_email")

# The anomaly monitor needs Cost Explorer, and turning that on is the
# organization's management account's to do, never this script's.
# Cost Explorer answers in us-east-1 only, whatever the environment's region.
say "+ aws ce get-anomaly-monitors --region us-east-1  (answers once Cost Explorer is on for the account)"
if $dry_run; then
  anomaly_monitor="<true once Cost Explorer answers>"
elif aws ce get-anomaly-monitors --region us-east-1 --max-results 1 >/dev/null 2>&1; then
  anomaly_monitor=true
else
  anomaly_monitor=false
  say "note: Cost Explorer is not on for account $account_id, so the anomaly monitor is left out; the budget is not. Turn Cost Explorer on from the organization's management account, then run this again."
fi
bootstrap_vars+=(-var "anomaly_monitor=$anomaly_monitor")
if [ "$environment" = "staging" ]; then
  # A bucket name is global, so asking for production's from staging's
  # account answers 403 when it exists and 404 when it does not.
  production_bucket="tadas-state-$(config .environments.production.account_id)"
  say "+ aws s3api head-bucket --bucket $production_bucket  (403 or 200: production exists, replicate into it)"
  if $dry_run; then
    replicate="<true once production's bucket exists>"
  elif probe="$(aws s3api head-bucket --bucket "$production_bucket" 2>&1)"; then
    replicate=true
  else
    case "$probe" in
      *403*|*Forbidden*) replicate=true ;;
      *404*|*"Not Found"*) replicate=false ;;
      *) refuse "cannot tell whether production's bucket exists: $probe" ;;
    esac
  fi
  bootstrap_vars+=(-var "replicate_to_production=$replicate")
  say "Replication into production: $replicate."
fi

if $dry_run || ! aws s3api head-bucket --bucket "$state_bucket" >/dev/null 2>&1; then
  # The bucket the state lives in is made by this root, so the first apply
  # holds its state locally, and the state moves into the bucket after.
  say "The state bucket does not exist yet: the root applies with local state, then its state moves into the bucket."
  say "+ write $bootstrap_root/backend_override.tf (terraform { backend \"local\" {} })"
  if ! $dry_run; then
    printf 'terraform {\n  backend "local" {}\n}\n' > "$bootstrap_root/backend_override.tf"
    trap 'rm -f "$bootstrap_root/backend_override.tf"' EXIT
  fi
  run terraform -chdir="$bootstrap_root" init -input=false
  check_account
  run terraform -chdir="$bootstrap_root" apply -input=false "${bootstrap_vars[@]}"
  say "+ rm $bootstrap_root/backend_override.tf"
  if ! $dry_run; then rm -f "$bootstrap_root/backend_override.tf"; trap - EXIT; fi
  run terraform -chdir="$bootstrap_root" init -input=false -migrate-state -force-copy "${backend_args[@]}"
  say "+ rm -f $bootstrap_root/terraform.tfstate $bootstrap_root/terraform.tfstate.backup"
  if ! $dry_run; then rm -f "$bootstrap_root/terraform.tfstate" "$bootstrap_root/terraform.tfstate.backup"; fi
else
  run terraform -chdir="$bootstrap_root" init -input=false -reconfigure "${backend_args[@]}"
  check_account
  run terraform -chdir="$bootstrap_root" apply -input=false "${bootstrap_vars[@]}"
fi

say "== 3. The delegation at Cloudflare: each public name's NS records name its zone here"
cloudflare_api=https://api.cloudflare.com/client/v4

# The token goes in a header and never on a printed line.
cloudflare() {
  local method="$1" path="$2" body="${3:-}"
  local args=(-sS --fail-with-body -X "$method" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json")
  [ -z "$body" ] || args+=(--data "$body")
  curl "${args[@]}" "$cloudflare_api$path"
}

if $dry_run; then
  say "+ cloudflare GET /zones?name=$domain"
  for name in "$api_domain_name" "$app_domain_name"; do
    say "+ cloudflare GET /zones/<zone id>/dns_records?type=NS&name=$name"
    say "+ cloudflare POST /zones/<zone id>/dns_records NS $name -> <each name server of $name>, and DELETE any other NS record there"
  done
else
  name_servers="$(terraform -chdir="$bootstrap_root" output -json name_servers)"
  say "+ cloudflare GET /zones?name=$domain"
  zone_id="$(cloudflare GET "/zones?name=$domain" | jq -er '.result[0].id')" \
    || refuse "Cloudflare holds no zone named $domain that the token can read"
  for name in "$api_domain_name" "$app_domain_name"; do
    wanted="$(printf '%s' "$name_servers" | jq -r --arg name "$name" '.[$name][]')"
    say "+ cloudflare GET /zones/$zone_id/dns_records?type=NS&name=$name"
    existing="$(cloudflare GET "/zones/$zone_id/dns_records?type=NS&name=$name&per_page=100")"
    for server in $wanted; do
      if printf '%s' "$existing" | jq -e --arg server "$server" '.result[] | select(.content == $server)' >/dev/null; then
        say "$name NS $server is there already."
      else
        say "+ cloudflare POST /zones/$zone_id/dns_records NS $name -> $server"
        cloudflare POST "/zones/$zone_id/dns_records" \
          "$(jq -nc --arg name "$name" --arg server "$server" '{type: "NS", name: $name, content: $server, ttl: 3600}')" >/dev/null
      fi
    done
    # A record left from a zone that was destroyed and made again points at
    # name servers that no longer answer for it.
    printf '%s' "$existing" | jq -r '.result[] | "\(.id) \(.content)"' | while read -r record_id server; do
      if ! printf '%s\n' "$wanted" | grep -qxF "$server"; then
        say "+ cloudflare DELETE /zones/$zone_id/dns_records/$record_id ($name NS $server)"
        cloudflare DELETE "/zones/$zone_id/dns_records/$record_id" >/dev/null
      fi
    done
  done
fi

say "== 4. The investigate profile, chained from the Identity Center profile"
aws_dir="$HOME/.aws"
aws_config="$aws_dir/config"
investigate_profile="tadas-$environment-investigate"
investigate_role="$(output_of investigate_role_arn)"

has_profile() {
  [ -f "$1" ] && grep -qxF "[$2]" "$1"
}

if has_profile "$aws_config" "profile $investigate_profile"; then
  say "$aws_config already has [profile $investigate_profile]; it is left as it is."
else
  say "+ append to $aws_config:"
  say "  [profile $investigate_profile]"
  say "  role_arn = $investigate_role"
  say "  source_profile = $sso_profile"
  say "  region = $region"
  if ! $dry_run; then
    mkdir -p "$aws_dir"
    printf '\n[profile %s]\nrole_arn = %s\nsource_profile = %s\nregion = %s\n' \
      "$investigate_profile" "$investigate_role" "$sso_profile" "$region" >> "$aws_config"
  fi
fi
has_profile "$aws_config" "profile $sso_profile" || say "note: $aws_config has no [profile $sso_profile]; the investigate profile chains from it, so sign-in (aws sso login --profile $sso_profile) needs it first."

say "== 5. The GitHub environments ($github_environments) of $(config .github_repository) and their variables"
# Each environment holds its own variables under the same names, so a job
# reads AWS_ROLE_ARN and gets the role of the environment it declared, and a
# staging job never holds a production value.
set_variables() {
  local github_environment="$1"
  shift
  local pair
  for pair in "$@"; do
    run gh variable set "${pair%%=*}" --env "$github_environment" --body "${pair#*=}"
  done
}

case "$environment" in
  staging)
    deploy_role="$(output_of deploy_role_arn)"
    run gh api -X PUT 'repos/{owner}/{repo}/environments/staging'
    set_variables staging \
      "AWS_ROLE_ARN=$deploy_role" \
      "TF_STATE_BUCKET=$state_bucket" \
      "API_DOMAIN_NAME=$api_domain_name" \
      "APP_DOMAIN_NAME=$app_domain_name" \
      "ALARM_EMAIL=$alarm_email"
    ;;
  production)
    plan_role="$(output_of plan_role_arn)"
    deploy_role="$(output_of deploy_role_arn)"
    # `production-plan` carries no rule: a reviewer on the plan would hold
    # the plan the reviewer is meant to read. `production` requires the
    # owner, and that reviewer is what gates the deploy credential.
    run gh api -X PUT 'repos/{owner}/{repo}/environments/production-plan'
    if $dry_run; then
      owner_id="<owner id>"
    else
      owner_id="$(gh api 'repos/{owner}/{repo}' -q .owner.id)"
    fi
    run gh api -X PUT 'repos/{owner}/{repo}/environments/production' -f 'reviewers[][type]=User' -F "reviewers[][id]=$owner_id"
    set_variables production-plan \
      "AWS_ROLE_ARN=$plan_role" \
      "TF_STATE_BUCKET=$state_bucket" \
      "API_DOMAIN_NAME=$api_domain_name" \
      "APP_DOMAIN_NAME=$app_domain_name" \
      "ALARM_EMAIL=$alarm_email"
    set_variables production \
      "AWS_ROLE_ARN=$deploy_role" \
      "TF_STATE_BUCKET=$state_bucket"
    ;;
esac

say "== 6. The operator's env file for $environment"
api_url="https://$api_domain_name"
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
  staging)
    run gh workflow run deploy-staging.yml --ref main
    ;;
  production)
    # Replication copies what staging pushes from the moment it is on, and
    # nothing before, so the first release is a commit staging built after.
    say "Production releases what staging built and replicated, so its first release waits for three things:"
    say "  1. scripts/cloud_create.sh staging, again: it finds production's bucket and turns the replication on."
    say "  2. A merge to main after that: deploy-staging builds it, and its images and portal build replicate here."
    say "  3. gh workflow run release.yml --ref main: the release, planned, approved in the production environment, applied."
    ;;
esac

say "== 8. When the deploy is green, the smoke test: one request, then its signals by request id"
say "id=\$(curl -s -o /dev/null -D - $api_url/v1/me | awk 'tolower(\$1) == \"x-request-id:\" { print \$2 }' | tr -d '\\r')"
say "uv run tadas-ops signals check --env $environment --request-id \"\$id\""
say "The environment root is $environment_root; the operator's file is $ops_file."
