output "database_url_secret_arn" {
  description = "Injected into every task as TADAS_DATABASE_URL."
  value       = aws_secretsmanager_secret.database_url.arn
  # A task (the migration first) reads the value; one started before the
  # version exists finds no AWSCURRENT and fails the first apply.
  depends_on = [aws_secretsmanager_secret_version.database_url]
}

output "application_prefix" {
  description = "TADAS_SECRETS_NAME_PREFIX for every process."
  value       = local.application_prefix
}

output "policy_arn" {
  description = "Attached to every task role; reads the application prefix only."
  value       = aws_iam_policy.application.arn
}

output "sentry_dsn_secret_arn" {
  description = "Injected into every task as TADAS_SENTRY_DSN; \"off\" until set, which leaves reporting off."
  value       = aws_secretsmanager_secret.sentry_dsn.arn
  depends_on  = [aws_secretsmanager_secret_version.sentry_dsn]
}
