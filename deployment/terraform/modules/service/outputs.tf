output "log_group_name" {
  description = "The log group every replica of this service writes to."
  value       = aws_cloudwatch_log_group.this.name
}
