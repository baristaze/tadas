output "url" {
  description = "TADAS_REDIS_URL for every process."
  value       = "rediss://${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
}
