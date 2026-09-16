output "log_group_name" {
  description = "The log group every replica of this service writes to."
  value       = aws_cloudwatch_log_group.this.name
}

output "task_definition_arn" {
  description = "The revision the service runs; a one-off run (a migration) uses the same one."
  value       = aws_ecs_task_definition.this.arn
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}
