output "load_balancer_dns_name" {
  description = "Where the API answers."
  value       = module.load_balancer.dns_name
}

# What deploy.yml needs to run the migration as a one-off task on the API
# image it just rolled out.

output "cluster_name" {
  value = module.cluster.name
}

output "api_task_definition_arn" {
  value = module.api.task_definition_arn
}

output "private_subnet_ids" {
  value = module.network.private_subnet_ids
}

output "app_security_group_id" {
  value = module.network.app_security_group_id
}
