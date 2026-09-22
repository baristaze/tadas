# Three kinds of secret live under one environment. The platform's own
# credentials (the four database URLs, the TOTP encryption key) are written
# here, write-only, and injected into tasks by the execution role.
# Application-managed secrets, the ones SecretsInterface reads at runtime,
# live under "<prefix>app/", which is the value of TADAS_SECRETS_NAME_PREFIX,
# so a process can never reach its own bootstrap credentials through the
# capability; that grant is read-only, as the task boundary in the account
# module is. The two operator tokens are the third kind: declared empty here,
# written by the grant task alone, and named outside the prefix, so no
# grant on the prefix reaches them.

data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  tags               = { "tadas:environment" = var.environment }
  application_prefix = "${var.prefix}app/"
  # A deleted secret keeps its name for the recovery window, so a nuke
  # followed by a create within it would be refused. Outside production the
  # window is none at all; production keeps thirty days, and the nuke's apply
  # (destroyable) lifts it on the way down.
  recovery_window_in_days = var.destroyable || var.environment != "production" ? 0 : 30
  secret_arn_prefix       = "arn:${data.aws_partition.current.partition}:secretsmanager:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:secret:"
}

# The database's four URLs, one per login. The master's is the secret the
# first release wrote under `database_url`, kept under that name: the master
# password exists for the run that set it and nowhere else, so a new secret
# could hold it only through a rotation. The migrate task alone reads it.
moved {
  from = aws_secretsmanager_secret.database_url
  to   = aws_secretsmanager_secret.database_master_url
}

moved {
  from = aws_secretsmanager_secret_version.database_url
  to   = aws_secretsmanager_secret_version.database_master_url
}

resource "aws_secretsmanager_secret" "database_master_url" {
  name                    = "${var.prefix}database_url"
  recovery_window_in_days = local.recovery_window_in_days
  tags                    = local.tags
}

# Write-only: the URL carries the password, and neither the state nor a plan
# may hold it. The version is the database module's password version, so a
# rotation writes both.
resource "aws_secretsmanager_secret_version" "database_master_url" {
  secret_id = aws_secretsmanager_secret.database_master_url.id
  # `ssl=require`: the connection is encrypted, never left to what the
  # driver and the server happen to agree on.
  secret_string_wo         = "postgresql+asyncpg://${var.database_username}:${urlencode(var.database_password)}@${var.database_address}:${var.database_port}/${var.database_name}?ssl=require"
  secret_string_wo_version = var.database_password_version
}

# The three logins the application connects as. Each password is generated
# for the run and written once per password version, write-only, into its
# URL; the migrate task's `ensure-logins` reads the URLs and sets each
# login's password from its own, so the secret is the one place a password
# is decided. Raising the version rotates the three with the master's.
locals {
  logins = {
    runtime   = "tadas_runtime"
    system    = "tadas_system"
    migration = "tadas_migration"
  }
}

ephemeral "random_password" "login" {
  for_each = local.logins

  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "login_url" {
  for_each = local.logins

  name                    = "${var.prefix}database_${each.key}_url"
  recovery_window_in_days = local.recovery_window_in_days
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "login_url" {
  for_each = local.logins

  secret_id                = aws_secretsmanager_secret.login_url[each.key].id
  secret_string_wo         = "postgresql+asyncpg://${each.value}:${urlencode(ephemeral.random_password.login[each.key].result)}@${var.database_address}:${var.database_port}/${var.database_name}?ssl=require"
  secret_string_wo_version = var.database_password_version
}

# The key the API encrypts each person's TOTP secret under: 32 random bytes,
# URL-safe base64 (a Fernet key). Written once and never again: a new key
# would leave every enrolled secret unreadable, so a rotation is a change of
# its own that re-encrypts, not a number raised here.
ephemeral "random_password" "totp_encryption_key" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "totp_encryption_key" {
  name                    = "${var.prefix}totp_encryption_key"
  recovery_window_in_days = local.recovery_window_in_days
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "totp_encryption_key" {
  secret_id                = aws_secretsmanager_secret.totp_encryption_key.id
  secret_string_wo         = replace(replace(base64encode(ephemeral.random_password.totp_encryption_key.result), "+", "-"), "/", "_")
  secret_string_wo_version = 1
}

# The Sentry-compatible DSN errors report to (sentry.io or a hosted GlitchTip).
# There is one tracker project for the product, and every environment holds the
# same project's DSN here: what separates the events is the environment each
# process sends on every event, not the project it sends to. The secret is per
# environment because a secret is per account and production's account cannot
# read staging's, so the one DSN is written into each account once.
# Terraform creates it as "off", which leaves reporting off (Secrets Manager
# refuses an empty value), and never writes it again: set the real value once with
#   aws secretsmanager put-secret-value --secret-id <prefix>sentry_dsn --secret-string <dsn>
resource "aws_secretsmanager_secret" "sentry_dsn" {
  name                    = "${var.prefix}sentry_dsn"
  recovery_window_in_days = local.recovery_window_in_days
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "sentry_dsn" {
  secret_id     = aws_secretsmanager_secret.sentry_dsn.id
  secret_string = "off"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

data "aws_iam_policy_document" "application" {
  statement {
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = ["${local.secret_arn_prefix}${local.application_prefix}*"]
  }
}

resource "aws_iam_policy" "application" {
  name   = "tadas-${var.environment}-secrets"
  policy = data.aws_iam_policy_document.application.json
  tags   = local.tags
}

# The operator tokens the grant task mints: the provisioner's (write) and the
# smoke job's (read). Declared with no value; `tadas-api grant-operator
# --mint-token` writes each, and nothing else can: the grant task's role is
# the one role given the policy below, and the deploy role reads them.
resource "aws_secretsmanager_secret" "operator_token" {
  for_each = toset(["provisioner", "smoke"])

  name                    = "tadas-${var.environment}-${each.key}-token"
  recovery_window_in_days = local.recovery_window_in_days
  tags                    = local.tags
}

data "aws_iam_policy_document" "operator_tokens" {
  statement {
    actions   = ["secretsmanager:PutSecretValue"]
    resources = [for secret in aws_secretsmanager_secret.operator_token : secret.arn]
  }
}

resource "aws_iam_policy" "operator_tokens" {
  name   = "tadas-${var.environment}-operator-tokens"
  policy = data.aws_iam_policy_document.operator_tokens.json
  tags   = local.tags
}
