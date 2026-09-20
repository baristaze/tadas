output "repository_urls" {
  description = "Image name to registry URL; the deploy workflow pushes here and passes the digest on."
  value       = { for name, repository in aws_ecr_repository.this : name => repository.repository_url }
}

# One role per environment, and one that only reads. Each is the value of the
# repository variable named beside it; a job that presents the wrong subject
# is refused by the role's trust whatever the variable holds.

output "staging_deploy_role_arn" {
  description = "Set as the AWS_STAGING_ROLE_ARN repository variable."
  value       = module.staging_deploy_role.arn
}

output "production_plan_role_arn" {
  description = "Set as the AWS_PRODUCTION_PLAN_ROLE_ARN repository variable."
  value       = aws_iam_role.plan_production.arn
}

output "production_deploy_role_arn" {
  description = "Set as the AWS_PRODUCTION_ROLE_ARN repository variable."
  value       = module.production_deploy_role.arn
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

# What the create script writes into ~/.aws/config, one profile per role per
# environment, chained from the operators user's key.

output "staging_investigate_role_arn" {
  description = "The role_arn of the tadas-staging-investigate profile."
  value       = module.staging_investigate_role.arn
}

output "production_investigate_role_arn" {
  description = "The role_arn of the tadas-production-investigate profile."
  value       = module.production_investigate_role.arn
}

output "operators_user_name" {
  description = "The IAM user the create script mints an access key for; the source_profile of every investigate profile."
  value       = aws_iam_user.operators.name
}

output "dns_name_servers" {
  description = "The zone's name servers, to set at the registrar once; empty when the zone is not created here."
  value       = var.create_dns_zone ? aws_route53_zone.this[0].name_servers : []
}
