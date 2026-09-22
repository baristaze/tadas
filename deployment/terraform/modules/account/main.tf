# What every environment's account holds before its first deploy: the image
# registry, the state bucket, GitHub's OIDC provider, the ceiling on every
# task role, the role an operator reads the environment under, the budget,
# and the two hosted zones its public names live in.
#
# Each environment has an account of its own, so none of this is shared
# between them. The account is the fence: a staging credential is a
# credential in another account, and nothing in production trusts it. The
# two bootstrap roots call this module, add the roles their own deploy
# workflow assumes, and wire the one direction anything crosses: staging's
# images and portal builds replicate into production.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  partition = data.aws_partition.current.partition
  account   = data.aws_caller_identity.current.account_id
  region    = data.aws_region.current.region

  # The account id makes the name unique across AWS without an input.
  state_bucket = "tadas-state-${local.account}"

  # A person signs in through IAM Identity Center; the permission set's role
  # sits under this path with a generated suffix, so it is matched by
  # pattern and never by a name someone copies in.
  operator_principal_arn_patterns = length(var.operator_principal_arn_patterns) > 0 ? var.operator_principal_arn_patterns : [
    "arn:${local.partition}:iam::${local.account}:role/aws-reserved/sso.amazonaws.com/*AWSReservedSSO_PowerUserAccess_*",
  ]
}

# Registry.

resource "aws_ecr_repository" "this" {
  for_each = toset(var.images)

  name                 = each.key
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name
  # Production runs whatever it was last released on, however many merges
  # ago, so the count alone would expire it. The production deploy tags each
  # digest it promotes `prod-<sha>`, and an image a rule of higher priority
  # selects is never expired by a lower one: the last ten releases stay, for
  # the tasks production replaces and for a rollback. In staging's account
  # no image carries the prefix and the first rule selects nothing.
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "keep the last 10 images production ran"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["prod-"]
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "keep the last 30 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 30
        }
        action = { type = "expire" }
      },
    ]
  })
}

# State.

resource "aws_s3_bucket" "state" {
  bucket = local.state_bucket
}

# Versioning keeps every earlier state, and replication requires it on both
# ends.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Credentials.
#
# One GitHub OIDC provider per account. The roles behind it are the
# bootstrap root's: which subjects an account trusts is what makes it
# staging's or production's.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

# The ceiling on every role a deploy run creates. A task role is made by the
# graph, which the deploy role applies, so without a boundary the deploy role
# could mint a role wider than itself and hand it to a task. This is what the
# `NoRoleWithoutTheTaskBoundary` fence requires be attached.

data "aws_iam_policy_document" "task_boundary" {
  statement {
    sid     = "ItsOwnBucketsAndQueues"
    actions = ["s3:*", "sqs:*"]
    resources = [
      "arn:${local.partition}:s3:::tadas-${var.environment}-*",
      "arn:${local.partition}:s3:::tadas-${var.environment}-*/*",
      "arn:${local.partition}:sqs:*:${local.account}:tadas-${var.environment}-*",
    ]
  }

  statement {
    sid       = "ItsOwnSecrets"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["arn:${local.partition}:secretsmanager:*:${local.account}:secret:tadas/${var.environment}/*"]
  }

  statement {
    sid = "ItsOwnLogStreams"
    actions = [
      "logs:CreateLogStream",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = ["arn:${local.partition}:logs:*:${local.account}:log-group:/tadas/${var.environment}/*"]
  }

  statement {
    sid       = "PullTheImageItRuns"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "TheImagesOfThisPlatform"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [for repository in aws_ecr_repository.this : repository.arn]
  }

  # What the collector sidecar emits.
  statement {
    sid = "Telemetry"
    actions = [
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
      "xray:PutTelemetryRecords",
      "xray:PutTraceSegments",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "Metrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["Tadas"]
    }
  }
}

resource "aws_iam_policy" "task_boundary" {
  # Deliberately not "tadas-<environment>-...": that shape is what a deploy
  # role may write, and a boundary it could rewrite is no boundary.
  name        = "tadas-task-boundary-${var.environment}"
  description = "The ceiling on every role the ${var.environment} deploy role creates."
  policy      = data.aws_iam_policy_document.task_boundary.json
}

# The operators. A person signs in through IAM Identity Center and assumes
# the investigate role from there; an agent runs under the same profile. No
# IAM user and no access key: every credential here is short-lived.

module "investigate_role" {
  source = "../investigate_role"

  environment       = var.environment
  other_environment = var.other_environment

  state_bucket     = aws_s3_bucket.state.bucket
  state_key_prefix = var.state_key_prefix

  operator_principal_arn_patterns = local.operator_principal_arn_patterns
}

# Cost.
#
# The budget is the catch-all every other bound sits under: the owner hears
# at half of it, at most of it, at all of it, and when the forecast crosses
# it. The anomaly monitor watches each service's spend beside it and reports
# a jump the budget would only show at month's end. One account, one
# environment, so the account's bill is the environment's. The monitor needs
# Cost Explorer, which the organization turns on; until it does, the
# bootstrap script leaves the monitor out and says so.

resource "aws_budgets_budget" "monthly" {
  name         = "tadas-${var.environment}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [
      { type = "ACTUAL", threshold = 50 },
      { type = "ACTUAL", threshold = 80 },
      { type = "ACTUAL", threshold = 100 },
      { type = "FORECASTED", threshold = 100 },
    ]

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value.type
      subscriber_email_addresses = [var.owner_email]
    }
  }
}

resource "aws_ce_anomaly_monitor" "services" {
  count = var.anomaly_monitor ? 1 : 0

  name              = "tadas-${var.environment}-services"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "owner" {
  count = var.anomaly_monitor ? 1 : 0

  name             = "tadas-${var.environment}-anomalies"
  frequency        = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.services[0].arn]

  subscriber {
    type    = "EMAIL"
    address = var.owner_email
  }

  # Below this an anomaly is noise on a budget this size.
  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(var.anomaly_impact_usd)]
    }
  }
}

# The zones.
#
# The domain is registered at Cloudflare, and a domain Cloudflare registers
# keeps Cloudflare's name servers, so the domain's own zone stays there. Each
# public name is delegated to a zone of its own here instead: the name's
# records sit at that zone's apex, and the zone belongs to one account. The
# bootstrap script writes each zone's name servers into Cloudflare as NS
# records, once.

resource "aws_route53_zone" "this" {
  for_each = toset([var.api_domain_name, var.app_domain_name])

  name    = each.key
  comment = "Tadas ${var.environment}: ${each.key}, delegated from the domain's zone at Cloudflare"
}
