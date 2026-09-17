output "url" {
  description = "TADAS_VALKEY_URL for every process."
  value       = "valkeys://${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
}
