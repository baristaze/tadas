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
