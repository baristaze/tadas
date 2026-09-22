# Each URL output waits for its version: a task (the migration first) reads
# the value, and one started before the version exists finds no AWSCURRENT
# and fails the first apply.

output "database_url_secret_arn" {
  description = "The runtime login's URL: TADAS_DATABASE_URL in every task."
  value       = aws_secretsmanager_secret.login_url["runtime"].arn
  depends_on  = [aws_secretsmanager_secret_version.login_url]
}

output "database_system_url_secret_arn" {
  description = "The system login's URL: TADAS_DATABASE_SYSTEM_URL in every task."
  value       = aws_secretsmanager_secret.login_url["system"].arn
  depends_on  = [aws_secretsmanager_secret_version.login_url]
}

output "database_migration_url_secret_arn" {
  description = "The migration login's URL: TADAS_DATABASE_MIGRATION_URL, in the migrate task only."
  value       = aws_secretsmanager_secret.login_url["migration"].arn
  depends_on  = [aws_secretsmanager_secret_version.login_url]
}

output "database_master_url_secret_arn" {
  description = "The master user's URL: TADAS_DATABASE_MASTER_URL, in the migrate task only."
  value       = aws_secretsmanager_secret.database_master_url.arn
  depends_on  = [aws_secretsmanager_secret_version.database_master_url]
}

output "totp_encryption_key_secret_arn" {
  description = "Injected into the API as TADAS_TOTP_ENCRYPTION_KEY."
  value       = aws_secretsmanager_secret.totp_encryption_key.arn
  depends_on  = [aws_secretsmanager_secret_version.totp_encryption_key]
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
  description = "Injected into every task as TADAS_SENTRY_DSN; the product's one project, the same DSN in every environment, and \"off\" until set, which leaves reporting off."
  value       = aws_secretsmanager_secret.sentry_dsn.arn
  depends_on  = [aws_secretsmanager_secret_version.sentry_dsn]
}

output "operator_token_secret_names" {
  description = "The two token secrets by kind (provisioner, smoke); empty until the grant task mints one."
  value       = { for kind, secret in aws_secretsmanager_secret.operator_token : kind => secret.name }
}

output "operator_tokens_policy_arn" {
  description = "PutSecretValue on the two token secrets and nothing else; the grant task's role alone carries it."
  value       = aws_iam_policy.operator_tokens.arn
}
