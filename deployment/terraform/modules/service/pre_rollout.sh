#!/usr/bin/env bash
# Run commands in order, each as a one-off task on a task definition, and
# stop at the first that fails. Terraform runs it from the service module
# before the service rolls to a new task definition (the API's: the logins,
# then the migration); the inputs arrive as environment variables from the
# provisioner, and the credentials are the ones the apply runs with.
# COMMANDS is a JSON array of commands, each a JSON array of words.
set -euo pipefail

: "${CLUSTER:?}" "${TASK_DEFINITION:?}" "${SUBNETS:?}" "${SECURITY_GROUPS:?}" "${CONTAINER:?}" "${COMMANDS:?}"

run_one() {
  local command="$1" overrides task_arn exit_code reason
  overrides="$(jq -cn --arg name "$CONTAINER" --argjson command "$command" \
    '{containerOverrides: [{name: $name, command: $command}]}')"

  task_arn="$(aws ecs run-task \
    --cluster "$CLUSTER" \
    --task-definition "$TASK_DEFINITION" \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SECURITY_GROUPS],assignPublicIp=DISABLED}" \
    --overrides "$overrides" \
    --query 'tasks[0].taskArn' --output text)"

  echo "pre-rollout task $task_arn ($command) started on $CLUSTER"
  aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$task_arn"

  # The exit code is read from the container by name, never by position: a
  # task definition may carry a sidecar, and ECS does not order `containers`.
  exit_code="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task_arn" \
    --query "tasks[0].containers[?name=='$CONTAINER'] | [0].exitCode" --output text)"
  reason="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task_arn" \
    --query 'tasks[0].stoppedReason' --output text)"

  if [ "$exit_code" != "0" ]; then
    echo "pre-rollout task failed: $command exited $exit_code ($reason); the service keeps its current tasks" >&2
    exit 1
  fi
  echo "pre-rollout task finished: $command"
}

while IFS= read -r command; do
  run_one "$command"
done < <(jq -c '.[]' <<<"$COMMANDS")
