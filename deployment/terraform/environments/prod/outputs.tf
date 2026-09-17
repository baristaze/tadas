output "load_balancer_dns_name" {
  description = "The API's load balancer; browsers use portal_url instead."
  value       = module.load_balancer.dns_name
}

output "portal_url" {
  description = "Where the portal answers, and the API under /v1."
  value       = module.portal.url
}

# What deploy.yml needs to publish the portal build.

output "portal_bucket" {
  value = module.portal.bucket_name
}

output "portal_distribution_id" {
  value = module.portal.distribution_id
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
