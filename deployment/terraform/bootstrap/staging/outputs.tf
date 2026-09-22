# What scripts/cloud_create.sh reads back: the GitHub variables of the
# `staging` environment, the profile it writes, and the delegation it makes
# at Cloudflare.

output "account_id" {
  value = module.account.account_id
}

output "deploy_role_arn" {
  description = "The AWS_ROLE_ARN variable of the staging GitHub environment."
  value       = module.deploy_role.arn
}

output "state_bucket" {
  description = "The TF_STATE_BUCKET variable of the staging GitHub environment."
  value       = module.account.state_bucket
}

output "investigate_role_arn" {
  description = "The role_arn of the tadas-staging-investigate profile."
  value       = module.account.investigate_role_arn
}

output "repository_urls" {
  value = module.account.repository_urls
}

output "name_servers" {
  description = "Each public name to its zone's name servers, written at Cloudflare as NS records."
  value       = module.account.name_servers
}

output "replicating_to_production" {
  value = var.replicate_to_production
}
