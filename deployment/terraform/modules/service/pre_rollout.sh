#!/usr/bin/env bash
# Run one command as a one-off task on a task definition and fail if it
# fails. Terraform runs it from the service module before the service rolls
# to a new task definition (the API's migration); the inputs arrive as
# environment variables from the provisioner, and the credentials are the
# ones the apply runs with.
set -euo pipefail

: "${CLUSTER:?}" "${TASK_DEFINITION:?}" "${SUBNETS:?}" "${SECURITY_GROUPS:?}" "${CONTAINER:?}" "${COMMAND:?}"

overrides="$(jq -cn --arg name "$CONTAINER" --argjson command "$COMMAND" \
  '{containerOverrides: [{name: $name, command: $command}]}')"

task_arn="$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$TASK_DEFINITION" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SECURITY_GROUPS],assignPublicIp=DISABLED}" \
  --overrides "$overrides" \
  --query 'tasks[0].taskArn' --output text)"

echo "pre-rollout task $task_arn ($COMMAND) started on $CLUSTER"
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$task_arn"

# The task runs the command beside the telemetry sidecar, and ECS does not
# order `containers`, so the exit code is read from the container by name: a
# collector that exits 0 must not pass a migration that failed, and one killed
# on shutdown (137) must not fail a migration that worked.
exit_code="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task_arn" \
  --query "tasks[0].containers[?name=='$CONTAINER'] | [0].exitCode" --output text)"
reason="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task_arn" \
  --query 'tasks[0].stoppedReason' --output text)"

if [ "$exit_code" != "0" ]; then
  echo "pre-rollout task failed: exit code $exit_code ($reason); the service keeps its current tasks" >&2
  exit 1
fi
echo "pre-rollout task finished"
