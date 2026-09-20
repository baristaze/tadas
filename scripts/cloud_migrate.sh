#!/usr/bin/env bash
# Run `tadas-api migrate --all` once, as a one-off task on the API task
# definition an environment root just applied, and fail if it fails. The
# deploys run the migration inside the apply, before the services roll; this
# is the by-hand runner, from the repo root with the AWS session that applied
# the environment.
#
#   scripts/cloud_migrate.sh deployment/terraform/environments/staging
set -euo pipefail

root="${1:?usage: cloud_migrate.sh <terraform environment dir>}"

cluster="$(terraform -chdir="$root" output -raw cluster_name)"
task_definition="$(terraform -chdir="$root" output -raw api_task_definition_arn)"
subnets="$(terraform -chdir="$root" output -json private_subnet_ids | jq -r 'join(",")')"
security_group="$(terraform -chdir="$root" output -raw app_security_group_id)"

task_arn="$(aws ecs run-task \
  --cluster "$cluster" \
  --task-definition "$task_definition" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$security_group],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"api","command":["tadas-api","migrate","--all"]}]}' \
  --query 'tasks[0].taskArn' --output text)"

echo "migration task $task_arn started on $cluster"
aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$task_arn"

# By name, not by position: the task definition also carries the telemetry
# sidecar and ECS does not order `containers`.
exit_code="$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
  --query "tasks[0].containers[?name=='api'] | [0].exitCode" --output text)"
reason="$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
  --query 'tasks[0].stoppedReason' --output text)"

if [ "$exit_code" != "0" ]; then
  echo "migration failed: exit code $exit_code ($reason)" >&2
  exit 1
fi
echo "migration applied"
