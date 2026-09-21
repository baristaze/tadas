# Two kinds of secret live under one environment prefix. The platform's own
# credentials (the database URL) are written here and injected into tasks by
# the execution role. Application-managed secrets, the ones SecretsInterface
# reads at runtime, live under "<prefix>app/", which is the value of
# TADAS_SECRETS_NAME_PREFIX, so a process can never reach its own bootstrap
# credentials through the capability. The grant is read-only, as the task
# boundary in `shared` is: no code writes a secret at runtime yet, and the
# change that makes one does widen both, together.

data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  tags               = { "tadas:environment" = var.environment }
  application_prefix = "${var.prefix}app/"
  # A deleted secret keeps its name for the recovery window, so a nuke
  # followed by a create within it would be refused; the nuke's apply sets
  # destroyable, and the delete that follows is immediate.
  recovery_window_in_days = var.destroyable ? 0 : 30
  secret_arn_prefix       = "arn:${data.aws_partition.current.partition}:secretsmanager:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:secret:"
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.prefix}database_url"
  recovery_window_in_days = local.recovery_window_in_days
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = var.database_url
}

# The Sentry-compatible DSN errors report to (sentry.io or a hosted GlitchTip).
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
