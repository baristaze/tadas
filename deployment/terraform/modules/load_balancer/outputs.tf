output "dns_name" {
  value = aws_lb.this.dns_name
}

output "zone_id" {
  description = "The load balancer's hosted zone, for an alias record."
  value       = aws_lb.this.zone_id
}

output "target_group_arn" {
  description = "Handed to the API service instance."
  value       = aws_lb_target_group.api.arn
}
