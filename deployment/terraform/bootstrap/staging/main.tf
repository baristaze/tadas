# Staging's account, before its first deploy: everything the `account`
# module holds, the role `deploy-staging.yml` assumes, and the replication
# that carries what staging builds into production's account.
#
# scripts/cloud_create.sh applies this root, once and then again after
# production's root exists: the replication needs production's artifacts
# bucket to be there first, so the script turns it on only when it finds it.

locals {
  config     = jsondecode(file("${path.module}/../../../cloud/environments.json"))
  staging    = local.config.environments.staging
  production = local.config.environments.production
}

data "aws_partition" "current" {}

module "account" {
  source = "../../modules/account"

  environment       = "staging"
  other_environment = "production"
  state_key_prefix  = "environments/staging"

  api_domain_name = local.staging.api_domain_name
  app_domain_name = local.staging.app_domain_name

  owner_email        = var.owner_email
  monthly_budget_usd = var.monthly_budget_usd
  anomaly_monitor    = var.anomaly_monitor
}

# The one credential a merge to `main` holds: staging's, in staging's
# account. It trusts one subject, a job of this repository that declares
# `environment: staging` and runs on `main`.
module "deploy_role" {
  source = "../../modules/deploy_role"

  environment       = "staging"
  other_environment = "production"

  github_repository  = local.config.github_repository
  github_environment = "staging"
  github_ref         = "refs/heads/main"
  oidc_provider_arn  = module.account.oidc_provider_arn

  state_bucket     = module.account.state_bucket
  artifacts_bucket = module.account.artifacts_bucket
  state_key_prefix = "environments/staging"

  image_repositories = module.account.repository_names
  # Staging is the only environment that builds; it keeps the portal build by
  # commit, and production reads the copy replicated into its own bucket.
  push_images         = true
  write_portal_builds = true

  dns_record_patterns = flatten([
    for name in [local.staging.api_domain_name, local.staging.app_domain_name] : [name, "*.${name}"]
  ])

  task_boundary_policy_arn = module.account.task_boundary_policy_arn
}

# Replication.
#
# Production never reads staging's account. What it releases is a copy in its
# own: ECR copies every image staging pushes into production's registry,
# digest for digest, and S3 copies every portal build staging keeps into
# production's artifacts bucket, which holds no state. Production's bootstrap root grants the two
# writes; nothing in production trusts anything else from here, and
# tearing staging down leaves production's copies where they are.

locals {
  production_artifacts_bucket_arn = "arn:${data.aws_partition.current.partition}:s3:::tadas-artifacts-${local.production.account_id}"
}

resource "aws_ecr_replication_configuration" "to_production" {
  count = var.replicate_to_production ? 1 : 0

  replication_configuration {
    rule {
      destination {
        region      = local.config.region
        registry_id = local.production.account_id
      }

      repository_filter {
        filter      = "tadas-"
        filter_type = "PREFIX_MATCH"
      }
    }
  }
}

data "aws_iam_policy_document" "replication_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
  }
}

# Named outside `tadas-staging-*`, the prefix the deploy role may write, and
# denied to it by name.
resource "aws_iam_role" "replication" {
  count = var.replicate_to_production ? 1 : 0

  name                 = "tadas-replication-staging"
  description          = "Copies staging's portal builds into production's artifacts bucket."
  assume_role_policy   = data.aws_iam_policy_document.replication_assume.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "replication" {
  statement {
    sid       = "ReadTheReplicationRule"
    actions   = ["s3:GetReplicationConfiguration", "s3:ListBucket"]
    resources = [module.account.artifacts_bucket_arn]
  }

  statement {
    sid = "ReadThePortalBuilds"
    actions = [
      "s3:GetObjectVersionAcl",
      "s3:GetObjectVersionForReplication",
      "s3:GetObjectVersionTagging",
    ]
    resources = ["${module.account.artifacts_bucket_arn}/builds/portal/*"]
  }

  statement {
    sid = "WriteThemIntoProduction"
    actions = [
      "s3:ObjectOwnerOverrideToBucketOwner",
      "s3:ReplicateDelete",
      "s3:ReplicateObject",
      "s3:ReplicateTags",
    ]
    resources = ["${local.production_artifacts_bucket_arn}/builds/portal/*"]
  }
}

resource "aws_iam_role_policy" "replication" {
  count = var.replicate_to_production ? 1 : 0

  name   = "replicate-portal-builds"
  role   = aws_iam_role.replication[0].id
  policy = data.aws_iam_policy_document.replication.json
}

resource "aws_s3_bucket_replication_configuration" "to_production" {
  count = var.replicate_to_production ? 1 : 0

  bucket = module.account.artifacts_bucket
  role   = aws_iam_role.replication[0].arn

  rule {
    id     = "portal-builds"
    status = "Enabled"

    filter {
      prefix = "builds/portal/"
    }

    delete_marker_replication {
      status = "Disabled"
    }

    destination {
      bucket  = local.production_artifacts_bucket_arn
      account = local.production.account_id

      access_control_translation {
        owner = "Destination"
      }
    }
  }
}
