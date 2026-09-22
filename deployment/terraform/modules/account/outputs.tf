output "account_id" {
  value = local.account
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "state_bucket_arn" {
  value = aws_s3_bucket.state.arn
}

output "artifacts_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "artifacts_bucket_arn" {
  value = aws_s3_bucket.artifacts.arn
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github.arn
}

output "task_boundary_policy_arn" {
  value = aws_iam_policy.task_boundary.arn
}

output "repository_names" {
  value = [for repository in aws_ecr_repository.this : repository.name]
}

output "repository_urls" {
  description = "Image name to registry URL."
  value       = { for name, repository in aws_ecr_repository.this : name => repository.repository_url }
}

output "investigate_role_arn" {
  value = module.investigate_role.arn
}

output "name_servers" {
  description = "Each public name to its zone's name servers: the NS records the bootstrap script writes at Cloudflare."
  value       = { for name, zone in aws_route53_zone.this : name => zone.name_servers }
}
