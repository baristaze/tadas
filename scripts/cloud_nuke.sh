#!/usr/bin/env bash
# Destroy an environment, as the administrator. The `ops-cloud-deployment-nuke`
# skill narrates this script; the script is the hands.
#
#   scripts/cloud_nuke.sh staging [--dry-run]
#   scripts/cloud_nuke.sh production --confirm production [--dry-run]
#
# Staging goes on the word. Production refuses unless two things hold: its
# name is typed after `--confirm`, and `environments/prod/main.tf` on
# `origin/main` already reads `database_deletion_protection = false`, so the
# destruction of production is itself a pull request a person read.
#
# The run applies the environment root once with `destroyable=true` (buckets
# empty on destroy, the database skips its final snapshot and drops its
# protection), destroys it, and prints what remains. It prints every command
# before it runs it, and `--dry-run` prints them without running anything.
#
# Inputs, as flags or as environment variables:
#   --profile        AWS_PROFILE       the administrator profile, tadas-admin
#   --dns-zone-name  DNS_ZONE_NAME     the hosted zone, e.g. tadas.fyi
#   --alarm-email    ALARM_EMAIL       the address the root's alarms go to
#   --state-bucket   TF_STATE_BUCKET   the state bucket every root shares
#   --region         AWS_REGION        default us-east-1
set -euo pipefail

usage() {
  sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

refuse() {
  echo "refused: $*" >&2
  exit 2
}

environment=""
confirm=""
dry_run=false
profile="${AWS_PROFILE:-}"
dns_zone_name="${DNS_ZONE_NAME:-}"
alarm_email="${ALARM_EMAIL:-}"
state_bucket="${TF_STATE_BUCKET:-}"
region="${AWS_REGION:-us-east-1}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=true ;;
    --confirm) confirm="${2:-}"; shift ;;
    --profile) profile="${2:-}"; shift ;;
    --dns-zone-name) dns_zone_name="${2:-}"; shift ;;
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
  staging)
    root="environments/staging"
    api_domain_name="api.staging.$dns_zone_name"
    app_domain_name="app.staging.$dns_zone_name"
    ;;
  production)
    root="environments/prod"
    api_domain_name="api.$dns_zone_name"
    app_domain_name="app.$dns_zone_name"
    ;;
  "") usage ;;
  *) refuse "the environment is staging or production, not '$environment'" ;;
esac

[ "$profile" = "tadas-admin" ] || refuse "this runs under the tadas-admin profile only (AWS_PROFILE or --profile); it holds '${profile:-nothing}'"

missing=""
[ -n "$dns_zone_name" ] || missing="$missing DNS_ZONE_NAME"
[ -n "$alarm_email" ] || missing="$missing ALARM_EMAIL"
[ -n "$state_bucket" ] || missing="$missing TF_STATE_BUCKET"
[ -z "$missing" ] || refuse "missing:$missing (as flags or environment variables)"

cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
export AWS_PROFILE="$profile"

if [ "$environment" = "production" ]; then
  # Two things, and both are read here rather than trusted: the typed name,
  # and the merged change. `origin/main` is what merged; the working tree is
  # what someone might have edited a minute ago.
  [ "$confirm" = "production" ] || refuse "production is destroyed only behind its typed name: pass --confirm production"
  if ! $dry_run; then git fetch --quiet origin main || true; fi
  main_root="$(git show origin/main:deployment/terraform/environments/prod/main.tf 2>/dev/null)" \
    || refuse "cannot read environments/prod/main.tf on origin/main; fetch it, then run again"
  printf '%s\n' "$main_root" | grep -Eq '^\s*database_deletion_protection\s*=\s*false\s*$' \
    || refuse "environments/prod/main.tf on origin/main does not read database_deletion_protection = false; lift it in a pull request, merge it, then run again"
fi

run() {
  printf '+ %s\n' "$*"
  if ! $dry_run; then "$@"; fi
}

say() {
  printf '%s\n' "$*"
}

say "== 1. Who am I"
run aws sts get-caller-identity --profile "$profile"

say "== 2. The environment root, as it is deployed"
root_dir="deployment/terraform/$root"
run terraform -chdir="$root_dir" init -input=false \
  -backend-config="bucket=$state_bucket" \
  -backend-config="key=$root/terraform.tfstate" \
  -backend-config="region=$region" \
  -backend-config="use_lockfile=true"

# The images the environment runs are in its state; the apply below must
# pass the same ones, or it would roll the services on the way down.
image_in_state() {
  terraform -chdir="$root_dir" show -json | jq -r --arg name "$1" '
    [.. | objects | select(.type? == "aws_ecs_task_definition")
     | .values.container_definitions | fromjson | .[] | select(.name == $name) | .image] | first // empty'
}
if $dry_run; then
  api_image="<api image in state>"
  maintenance_image="<maintenance image in state>"
else
  api_image="$(image_in_state api)"
  maintenance_image="$(image_in_state maintenance)"
  [ -n "$api_image" ] && [ -n "$maintenance_image" ] || refuse "the state holds no task definitions; nothing to destroy, or the backend is wrong"
fi

root_vars=(
  -var "api_image=$api_image"
  -var "maintenance_image=$maintenance_image"
  -var "dns_zone_name=$dns_zone_name"
  -var "api_domain_name=$api_domain_name"
  -var "app_domain_name=$app_domain_name"
  -var "alarm_email=$alarm_email"
  -var "destroyable=true"
)

say "== 3. Lift the protections: buckets empty on destroy, the database skips its snapshot"
run terraform -chdir="$root_dir" apply -input=false -auto-approve "${root_vars[@]}"

say "== 4. Destroy $environment"
run terraform -chdir="$root_dir" destroy -input=false -auto-approve "${root_vars[@]}"

say "== 5. What remains"
say "- the hosted zone $dns_zone_name and its name servers at the registrar (shared root)"
say "- the state prefix $root/ and plans/$root/ in s3://$state_bucket (empty the prefix by hand if the environment is not coming back)"
say "- the portal builds under builds/portal/ in s3://$state_bucket"
say "- the images in the registry (shared root; the lifecycle policy keeps the last 30, and the last 10 tagged prod-)"
say "- the shared roles, the operators user, the budget, and the anomaly monitor (shared root)"
say "- $HOME/.config/tadas/ops/$environment.env, and the profiles in $HOME/.aws"
