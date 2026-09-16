# Two kinds of secret live under one environment prefix. The platform's own
# credentials (the database URL) are written here and injected into tasks by
# the execution role. Application-managed secrets, the ones SecretsInterface
# reads and writes at runtime, live under "<prefix>app/", which is the value of
# TADAS_SECRETS_NAME_PREFIX, so a process can never rewrite its own bootstrap
# credentials through the capability.

data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  tags               = { "tadas:environment" = var.environment }
  application_prefix = "${var.prefix}app/"
  secret_arn_prefix  = "arn:${data.aws_partition.current.partition}:secretsmanager:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:secret:"
}

resource "aws_secretsmanager_secret" "database_url" {
  name = "${var.prefix}database_url"
  tags = local.tags
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = var.database_url
}

data "aws_iam_policy_document" "application" {
  statement {
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
      "secretsmanager:CreateSecret",
      "secretsmanager:PutSecretValue",
      "secretsmanager:DeleteSecret",
    ]
    resources = ["${local.secret_arn_prefix}${local.application_prefix}*"]
  }
}

resource "aws_iam_policy" "application" {
  name   = "tadas-${var.environment}-secrets"
  policy = data.aws_iam_policy_document.application.json
  tags   = local.tags
}
