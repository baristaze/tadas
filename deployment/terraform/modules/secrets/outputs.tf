output "database_url_secret_arn" {
  description = "Injected into every task as TADAS_DATABASE_URL."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "application_prefix" {
  description = "TADAS_SECRETS_NAME_PREFIX for every process."
  value       = local.application_prefix
}

output "policy_arn" {
  description = "Attached to every task role; covers the application prefix only."
  value       = aws_iam_policy.application.arn
}

output "sentry_dsn_secret_arn" {
  description = "Injected into every task as TADAS_SENTRY_DSN; \"off\" until set, which leaves reporting off."
  value       = aws_secretsmanager_secret.sentry_dsn.arn
}
