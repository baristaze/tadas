output "api_url" {
  description = "Where the API answers."
  value       = "https://${var.api_domain_name}"
}

output "portal_url" {
  description = "Where the portal answers."
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
