# Forwarded from the environment module, which is where they are described.

output "api_url" {
  description = "Where the API answers."
  value       = module.environment.api_url
}

output "portal_url" {
  description = "Where the portal answers."
  value       = module.environment.portal_url
}

# What the deploy workflows need to publish the portal build.

output "portal_bucket" {
  value = module.environment.portal_bucket
}

output "portal_distribution_id" {
  value = module.environment.portal_distribution_id
}

# What a by-hand migration needs to run as a one-off task on the API
# image it just rolled out.

output "cluster_name" {
  value = module.environment.cluster_name
}

output "api_task_definition_arn" {
  value = module.environment.api_task_definition_arn
}

output "private_subnet_ids" {
  value = module.environment.private_subnet_ids
}

output "app_security_group_id" {
  value = module.environment.app_security_group_id
}
