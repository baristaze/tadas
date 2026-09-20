# Account-level resources every environment shares: the image registry
# (production promotes the digests staging already ran, so both pull from the
# same repositories), the state bucket, the roles the deploy workflows assume
# through GitHub's OIDC provider, the roles a person or an agent reads an
# environment under, the operators' user, the budget, and the zone.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  partition = data.aws_partition.current.partition
  account   = data.aws_caller_identity.current.account_id

  # The environment names every process knows. The state keys differ from
  # them (`environments/prod` for `production`) and are named at each role.
  environments = ["staging", "production"]
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
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 30 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 30
      }
      action = { type = "expire" }
    }]
  })
}

# State.

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket
}

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
# One GitHub OIDC provider, and one role per environment behind it. The roles
# are separate because the credential is the boundary: a merge to `main`
# deploys staging with no approval by design, so whatever that run holds is
# what an unreviewed change holds. It must not be what owns production.
#
# Three subjects, three roles, no overlap:
#
#   environment:staging         -> tadas-deploy-staging      applies staging
#   environment:production-plan -> tadas-plan-production      reads and plans
#   environment:production      -> tadas-deploy-production    applies production
#
# A GitHub job presents `repo:<owner>/<name>:environment:<name>` only when it
# declares that environment, so the subject condition on each role is what
# binds it to the gate: the `production` environment holds a required
# reviewer, and a job that has not passed the reviewer never produces the
# subject the apply role trusts. The plan that the reviewer reads is made
# under `tadas-plan-production`, which can read production and write its own
# lock and plan file, and can change nothing.

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
  for_each = toset(local.environments)

  statement {
    sid     = "ItsOwnBucketsAndQueues"
    actions = ["s3:*", "sqs:*"]
    resources = [
      "arn:${local.partition}:s3:::tadas-${each.key}-*",
      "arn:${local.partition}:s3:::tadas-${each.key}-*/*",
      "arn:${local.partition}:sqs:*:${local.account}:tadas-${each.key}-*",
    ]
  }

  statement {
    sid       = "ItsOwnSecrets"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["arn:${local.partition}:secretsmanager:*:${local.account}:secret:tadas/${each.key}/*"]
  }

  statement {
    sid = "ItsOwnLogStreams"
    actions = [
      "logs:CreateLogStream",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = ["arn:${local.partition}:logs:*:${local.account}:log-group:/tadas/${each.key}/*"]
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
    resources = [
      for name in var.images :
      "arn:${local.partition}:ecr:*:${local.account}:repository/${name}"
    ]
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
  for_each = data.aws_iam_policy_document.task_boundary

  # Deliberately not "tadas-<environment>-...": that shape is what a deploy
  # role may write, and a boundary it could rewrite is no boundary.
  name        = "tadas-task-boundary-${each.key}"
  description = "The ceiling on every role the ${each.key} deploy role creates."
  policy      = each.value.json
}

module "staging_deploy_role" {
  source = "../modules/deploy_role"

  environment       = "staging"
  other_environment = "production"

  github_repository  = var.github_repository
  github_environment = "staging"
  github_ref         = "refs/heads/main"
  oidc_provider_arn  = aws_iam_openid_connect_provider.github.arn

  state_bucket           = aws_s3_bucket.state.bucket
  state_key_prefix       = "environments/staging"
  other_state_key_prefix = "environments/prod"

  image_repositories = var.images
  # Staging is the only environment that builds; it keeps the portal build by
  # commit, and production reads it.
  push_images         = true
  write_portal_builds = true

  dns_zone_name       = var.dns_zone_name
  dns_record_patterns = ["*.staging.${var.dns_zone_name}"]

  task_boundary_policy_arn = aws_iam_policy.task_boundary["staging"].arn
}

module "production_deploy_role" {
  source = "../modules/deploy_role"

  environment       = "production"
  other_environment = "staging"

  github_repository  = var.github_repository
  github_environment = "production"
  github_ref         = "refs/heads/release"
  oidc_provider_arn  = aws_iam_openid_connect_provider.github.arn

  state_bucket           = aws_s3_bucket.state.bucket
  state_key_prefix       = "environments/prod"
  other_state_key_prefix = "environments/staging"

  image_repositories  = var.images
  push_images         = false
  write_portal_builds = false

  dns_zone_name = var.dns_zone_name
  # Production's names sit at the base domain, so its pattern is the zone and
  # staging's names are subtracted by the deny beside it.
  dns_record_patterns        = ["*.${var.dns_zone_name}", var.dns_zone_name]
  denied_dns_record_patterns = ["*.staging.${var.dns_zone_name}"]

  task_boundary_policy_arn = aws_iam_policy.task_boundary["production"].arn
}

# The credential the jobs before the approval run under. It reads production
# and writes three things: the state lock Terraform takes while it plans, the
# plan file the reviewer approves, and nothing else. A plan reads the state,
# and the state holds the database password in clear, so this role sees
# production's secrets; what it cannot do is change production. That is the
# line the approval is there to hold.

data "aws_iam_policy_document" "plan_production_assume" {
  statement {
    sid     = "GitHubJobsInTheProductionPlanEnvironment"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:production-plan"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:ref"
      values   = ["refs/heads/release"]
    }
  }
}

resource "aws_iam_role" "plan_production" {
  name                 = "tadas-plan-production"
  description          = "Resolves the images and plans production, before the approval. Changes nothing."
  assume_role_policy   = data.aws_iam_policy_document.plan_production_assume.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "plan_production_read" {
  role       = aws_iam_role.plan_production.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "plan_production" {
  statement {
    sid       = "ListOnlyProductionsKeys"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["environments/prod/*", "builds/portal/*", "plans/environments/prod/*"]
    }
  }

  # Terraform takes the lock to plan and drops it again; the state beside it
  # is read, never written, because a plan does not persist state.
  statement {
    sid       = "TheStateLockWhileItPlans"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/environments/prod/*.tflock"]
  }

  statement {
    sid       = "TheSavedPlanTheReviewerApproves"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.state.arn}/plans/environments/prod/*"]
  }

  statement {
    sid       = "TheSecretsARefreshReads"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:${local.partition}:secretsmanager:*:${local.account}:secret:tadas/production/*"]
  }
}

resource "aws_iam_role_policy" "plan_production" {
  name   = "plan"
  role   = aws_iam_role.plan_production.id
  policy = data.aws_iam_policy_document.plan_production.json
}

data "aws_iam_policy_document" "plan_production_fences" {
  statement {
    sid       = "NothingBelongingToStaging"
    effect    = "Deny"
    actions   = ["*"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/tadas:environment"
      values   = ["staging"]
    }
  }

  statement {
    sid       = "NotStagingsState"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = ["${aws_s3_bucket.state.arn}/environments/staging/*"]
  }

  # ReadOnlyAccess is a read of the whole account; these are the two reads a
  # plan has no business making.
  statement {
    sid       = "NotStagingsSecrets"
    effect    = "Deny"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:${local.partition}:secretsmanager:*:${local.account}:secret:tadas/staging/*"]
  }

  statement {
    sid     = "NoWideningOfTheDeployCredentials"
    effect  = "Deny"
    actions = ["iam:*", "sts:AssumeRole"]
    resources = [
      "arn:${local.partition}:iam::${local.account}:role/tadas-deploy-*",
      "arn:${local.partition}:iam::${local.account}:role/tadas-plan-*",
      "arn:${local.partition}:iam::${local.account}:role/tadas-investigate-*",
      "arn:${local.partition}:iam::${local.account}:user/tadas-operators",
      "arn:${local.partition}:iam::${local.account}:policy/tadas-task-boundary-*",
    ]
  }
}

resource "aws_iam_role_policy" "plan_production_fences" {
  name   = "fences"
  role   = aws_iam_role.plan_production.id
  policy = data.aws_iam_policy_document.plan_production_fences.json
}

# The operators.
#
# One IAM user the agents run as, `tadas-operators`, whose only permission is
# to assume the investigate roles, and one investigate role per environment
# that reads everything there and writes nothing. A person's profiles chain
# from the user: `tadas-staging-investigate` is the user's key plus the
# staging role's ARN. No access key is declared here: the create script
# mints one and writes the profiles, so the secret lives in the person's home
# and never in a state file. When the team grows, IAM Identity Center's
# permission-set roles go into `operator_principal_arns` and nothing below
# the trust policy changes.

resource "aws_iam_user" "operators" {
  name = "tadas-operators"
}

data "aws_iam_policy_document" "operators" {
  statement {
    sid       = "AssumeTheInvestigateRolesAndNothingElse"
    actions   = ["sts:AssumeRole"]
    resources = ["arn:${local.partition}:iam::${local.account}:role/tadas-investigate-*"]
  }
}

resource "aws_iam_user_policy" "operators" {
  name   = "assume-investigate"
  user   = aws_iam_user.operators.name
  policy = data.aws_iam_policy_document.operators.json
}

module "staging_investigate_role" {
  source = "../modules/investigate_role"

  environment       = "staging"
  other_environment = "production"

  state_bucket           = aws_s3_bucket.state.bucket
  state_key_prefix       = "environments/staging"
  other_state_key_prefix = "environments/prod"

  operators_user_arn      = aws_iam_user.operators.arn
  operator_principal_arns = var.operator_principal_arns
}

module "production_investigate_role" {
  source = "../modules/investigate_role"

  environment       = "production"
  other_environment = "staging"

  state_bucket           = aws_s3_bucket.state.bucket
  state_key_prefix       = "environments/prod"
  other_state_key_prefix = "environments/staging"

  operators_user_arn      = aws_iam_user.operators.arn
  operator_principal_arns = var.operator_principal_arns
}

# Cost.
#
# The budget is the catch-all every other bound sits under: the owner hears
# at half of it, at most of it, at all of it, and when the forecast crosses
# it. The anomaly monitor watches each service's spend beside it and reports
# a jump the budget would only show at month's end. Both are account-wide;
# the environment tag on every resource is what splits a cost report.

resource "aws_budgets_budget" "monthly" {
  name         = "tadas-monthly"
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
  name              = "tadas-services"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "owner" {
  name             = "tadas-anomalies"
  frequency        = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.services.arn]

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

# The zone.
#
# Both environments' public names live in one hosted zone, and the
# environment roots read it by name. It is created here when the account is
# the zone's home; a zone that already exists elsewhere (delegated in from a
# registrar's account) sets `create_dns_zone` to false and the roots find it
# the same way. The name servers are an output because the registrar is the
# one place they go, by hand, once.

resource "aws_route53_zone" "this" {
  count = var.create_dns_zone ? 1 : 0

  name    = var.dns_zone_name
  comment = "Tadas: both environments' public names"
}
