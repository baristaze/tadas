output "repository_urls" {
  description = "Image name to registry URL; the deploy workflow pushes here and passes the digest on."
  value       = { for name, repository in aws_ecr_repository.this : name => repository.repository_url }
}

output "deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN repository variable."
  value       = aws_iam_role.deploy.arn
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}
