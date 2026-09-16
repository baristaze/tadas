output "prefix" {
  value = var.prefix
}

output "queue_urls" {
  value = { for name, queue in aws_sqs_queue.this : name => queue.url }
}

output "policy_arn" {
  description = "Attached to every task role that sends or consumes."
  value       = aws_iam_policy.use.arn
}
