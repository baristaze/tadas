output "dns_name" {
  value = aws_lb.this.dns_name
}

output "target_group_arn" {
  description = "Handed to the API service instance."
  value       = aws_lb_target_group.api.arn
}
