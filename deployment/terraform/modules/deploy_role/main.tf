# One environment's deploy role: the credential a job in that environment's
# GitHub environment assumes, and the only credential that can change it.
#
# Trust is the first boundary. The subject condition names a GitHub
# environment, not a branch: a job that declares `environment: staging`
# presents `repo:<owner>/<name>:environment:staging` and nothing else does,
# so a job without the environment presents its ref instead and is refused.
# The ref condition is the second: staging runs on `main`, production on
# `release`, and a token from any other ref is refused whatever environment
# it declares.
#
# Permission is the second boundary. AWS takes no resource ARN on the calls
# that make a network (there is no VPC to name before CreateVpc returns), so
# the allow side is the set of services this environment's graph declares and
# the deny side is what fences it: anything tagged as the other environment,
# the other environment's state, the account-level resources `shared` owns,
# and any path by which this role could widen itself. Every name in the graph
# carries the environment (`tadas-<environment>`, `tadas/<environment>/`,
# `/tadas/<environment>/`), which is what makes the resource-level scoping
# below possible at all.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  partition = data.aws_partition.current.partition
  account   = data.aws_caller_identity.current.account_id
  region    = data.aws_region.current.region

  # Every name the graph gives a resource starts with one of these three.
  name_prefix   = "tadas-${var.environment}"
  secret_prefix = "tadas/${var.environment}/"
  log_prefix    = "/tadas/${var.environment}/"

  image_repository_arns = [
    for name in var.image_repositories :
    "arn:${local.partition}:ecr:${local.region}:${local.account}:repository/${name}"
  ]

  state_bucket_arn = "arn:${local.partition}:s3:::${var.state_bucket}"

  # The two managed policies the graph is allowed to attach: its own, and the
  # one AWS publishes for pulling an image and writing a log stream.
  attachable_policy_arns = [
    "arn:${local.partition}:iam::${local.account}:policy/${local.name_prefix}-*",
    "arn:${local.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
  ]
}

data "aws_iam_policy_document" "assume" {
  statement {
    sid     = "GitHubJobsInThisEnvironmentOnly"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Exactly one subject. A job of another repository, of a fork, or of this
    # repository without the environment declared does not produce it.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.github_environment}"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:ref"
      values   = [var.github_ref]
    }
  }
}

resource "aws_iam_role" "this" {
  name                 = "tadas-deploy-${var.environment}"
  description          = "Applies the ${var.environment} environment from GitHub Actions."
  assume_role_policy   = data.aws_iam_policy_document.assume.json
  max_session_duration = 3600
}

# What this environment's graph is made of. Three documents, because IAM
# caps one inline policy and this is one role's whole reach: what it reads,
# the platform it stands on, and the data it carries.

data "aws_iam_policy_document" "read" {
  statement {
    sid = "RefreshWhatTheGraphTouches"
    actions = [
      "acm:Describe*",
      "acm:Get*",
      "acm:List*",
      "cloudfront:Get*",
      "cloudfront:List*",
      "ec2:Describe*",
      "ecr:BatchGet*",
      "ecr:Describe*",
      "ecr:GetAuthorizationToken",
      "ecr:List*",
      "ecs:Describe*",
      "ecs:List*",
      "elasticache:Describe*",
      "elasticache:List*",
      "elasticloadbalancing:Describe*",
      "iam:Get*",
      "iam:List*",
      "kms:Describe*",
      "kms:List*",
      "logs:Describe*",
      "logs:List*",
      "rds:Describe*",
      "rds:List*",
      "route53:Get*",
      "route53:List*",
      "s3:Get*",
      "s3:List*",
      "secretsmanager:Describe*",
      "secretsmanager:List*",
      "sqs:Get*",
      "sqs:List*",
      "tag:Get*",
    ]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "graph_platform" {
  # A network call names no resource: CreateVpc has nothing to point at yet.
  # The list is what the network module declares and stops there, so this role
  # cannot start an instance, make an image, or mint a key pair.
  statement {
    sid = "Network"
    actions = [
      "ec2:AllocateAddress",
      "ec2:AssociateRouteTable",
      "ec2:AttachInternetGateway",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:CreateInternetGateway",
      "ec2:CreateNatGateway",
      "ec2:CreateRoute",
      "ec2:CreateRouteTable",
      "ec2:CreateSecurityGroup",
      "ec2:CreateSubnet",
      "ec2:CreateTags",
      "ec2:CreateVpc",
      "ec2:DeleteInternetGateway",
      "ec2:DeleteNatGateway",
      "ec2:DeleteRoute",
      "ec2:DeleteRouteTable",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteSubnet",
      "ec2:DeleteTags",
      "ec2:DeleteVpc",
      "ec2:DetachInternetGateway",
      "ec2:DisassociateRouteTable",
      "ec2:ModifySecurityGroupRules",
      "ec2:ModifySubnetAttribute",
      "ec2:ModifyVpcAttribute",
      "ec2:ReleaseAddress",
      "ec2:ReplaceRoute",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
    ]
    resources = ["*"]
  }

  statement {
    sid = "LoadBalancerAndCertificates"
    actions = [
      "acm:AddTagsToCertificate",
      "acm:DeleteCertificate",
      "acm:RemoveTagsFromCertificate",
      "acm:RenewCertificate",
      "acm:RequestCertificate",
      "elasticloadbalancing:AddTags",
      "elasticloadbalancing:Create*",
      "elasticloadbalancing:Delete*",
      "elasticloadbalancing:Deregister*",
      "elasticloadbalancing:Modify*",
      "elasticloadbalancing:Register*",
      "elasticloadbalancing:RemoveTags",
      "elasticloadbalancing:Set*",
    ]
    resources = ["*"]
  }

  statement {
    sid = "PortalDistribution"
    actions = [
      "cloudfront:CreateDistribution",
      "cloudfront:CreateFunction",
      "cloudfront:CreateInvalidation",
      "cloudfront:CreateOriginAccessControl",
      "cloudfront:CreateResponseHeadersPolicy",
      "cloudfront:DeleteDistribution",
      "cloudfront:DeleteFunction",
      "cloudfront:DeleteOriginAccessControl",
      "cloudfront:DeleteResponseHeadersPolicy",
      "cloudfront:PublishFunction",
      "cloudfront:TagResource",
      "cloudfront:UntagResource",
      "cloudfront:UpdateDistribution",
      "cloudfront:UpdateFunction",
      "cloudfront:UpdateOriginAccessControl",
      "cloudfront:UpdateResponseHeadersPolicy",
    ]
    resources = ["*"]
  }

  # The zone is shared, so the fence is the record name, not the zone: this
  # role changes the names under its own environment and the validation
  # records beneath them, and nothing else anyone has in the zone.
  statement {
    sid       = "OwnRecordNamesOnly"
    actions   = ["route53:ChangeResourceRecordSets"]
    resources = ["arn:${local.partition}:route53:::hostedzone/*"]

    condition {
      test     = "ForAllValues:StringLike"
      variable = "route53:ChangeResourceRecordSetsNormalizedRecordNames"
      values   = var.dns_record_patterns
    }
  }

  statement {
    sid = "ClusterAndServices"
    actions = [
      "ecs:CreateCluster",
      "ecs:CreateService",
      "ecs:DeleteCluster",
      "ecs:DeleteService",
      "ecs:DeregisterTaskDefinition",
      "ecs:PutClusterCapacityProviders",
      "ecs:RunTask",
      "ecs:StopTask",
      "ecs:TagResource",
      "ecs:UntagResource",
      "ecs:UpdateCluster",
      "ecs:UpdateClusterSettings",
      "ecs:UpdateService",
    ]
    resources = [
      "arn:${local.partition}:ecs:${local.region}:${local.account}:cluster/${local.name_prefix}",
      "arn:${local.partition}:ecs:${local.region}:${local.account}:service/${local.name_prefix}/*",
      "arn:${local.partition}:ecs:${local.region}:${local.account}:task/${local.name_prefix}/*",
      "arn:${local.partition}:ecs:${local.region}:${local.account}:task-definition/${local.name_prefix}-*:*",
    ]
  }

  # Registering a revision names no resource: there is no ARN until the call
  # returns one, and AWS offers no condition on the family, so this is the one
  # write in the graph that cannot be fenced to the environment. A revision in
  # another family is inert until something runs it, and running one is fenced
  # above.
  statement {
    sid       = "TaskDefinitionRevisions"
    actions   = ["ecs:RegisterTaskDefinition"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "graph_data" {
  statement {
    sid = "Database"
    actions = [
      "rds:AddTagsToResource",
      "rds:CreateDBInstance",
      "rds:CreateDBSnapshot",
      "rds:CreateDBSubnetGroup",
      "rds:DeleteDBInstance",
      "rds:DeleteDBSubnetGroup",
      "rds:ModifyDBInstance",
      "rds:ModifyDBSubnetGroup",
      "rds:RebootDBInstance",
      "rds:RemoveTagsFromResource",
    ]
    resources = [
      "arn:${local.partition}:rds:${local.region}:${local.account}:db:${local.name_prefix}",
      "arn:${local.partition}:rds:${local.region}:${local.account}:subgrp:${local.name_prefix}",
      "arn:${local.partition}:rds:${local.region}:${local.account}:snapshot:${local.name_prefix}-*",
      "arn:${local.partition}:rds:${local.region}:${local.account}:pg:*",
      "arn:${local.partition}:rds:${local.region}:${local.account}:og:*",
    ]
  }

  statement {
    sid = "Cache"
    actions = [
      "elasticache:AddTagsToResource",
      "elasticache:CreateCacheSubnetGroup",
      "elasticache:CreateReplicationGroup",
      "elasticache:DeleteCacheSubnetGroup",
      "elasticache:DeleteReplicationGroup",
      "elasticache:IncreaseReplicaCount",
      "elasticache:DecreaseReplicaCount",
      "elasticache:ModifyCacheSubnetGroup",
      "elasticache:ModifyReplicationGroup",
      "elasticache:RemoveTagsFromResource",
    ]
    resources = [
      "arn:${local.partition}:elasticache:${local.region}:${local.account}:replicationgroup:${local.name_prefix}",
      "arn:${local.partition}:elasticache:${local.region}:${local.account}:cluster:${local.name_prefix}-*",
      "arn:${local.partition}:elasticache:${local.region}:${local.account}:subnetgroup:${local.name_prefix}",
    ]
  }

  statement {
    sid = "Queues"
    actions = [
      "sqs:CreateQueue",
      "sqs:DeleteQueue",
      "sqs:SetQueueAttributes",
      "sqs:TagQueue",
      "sqs:UntagQueue",
    ]
    resources = ["arn:${local.partition}:sqs:${local.region}:${local.account}:${local.name_prefix}-*"]
  }

  statement {
    sid     = "BucketsAndPortalFiles"
    actions = ["s3:*"]
    resources = [
      "arn:${local.partition}:s3:::${local.name_prefix}-*",
      "arn:${local.partition}:s3:::${local.name_prefix}-*/*",
    ]
  }

  # The database password and the error-reporting DSN. A refresh reads them,
  # which is why a credential that can plan an environment is a credential
  # that can read its secrets; only these two prefixes, though.
  statement {
    sid       = "Secrets"
    actions   = ["secretsmanager:*"]
    resources = ["arn:${local.partition}:secretsmanager:${local.region}:${local.account}:secret:${local.secret_prefix}*"]
  }

  statement {
    sid = "LogGroups"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DeleteLogGroup",
      "logs:DeleteLogStream",
      "logs:PutLogEvents",
      "logs:PutRetentionPolicy",
      "logs:TagResource",
      "logs:UntagResource",
    ]
    resources = [
      "arn:${local.partition}:logs:${local.region}:${local.account}:log-group:${local.log_prefix}*",
      "arn:${local.partition}:logs:${local.region}:${local.account}:log-group:${local.log_prefix}*:*",
    ]
  }

  statement {
    sid = "TaskRolesAndTheirPolicies"
    actions = [
      "iam:AttachRolePolicy",
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:DeleteRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:UpdateRole",
    ]
    resources = ["arn:${local.partition}:iam::${local.account}:role/${local.name_prefix}-*"]
  }

  statement {
    sid = "ThePoliciesTheGraphDeclares"
    actions = [
      "iam:CreatePolicy",
      "iam:CreatePolicyVersion",
      "iam:DeletePolicy",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion",
      "iam:TagPolicy",
      "iam:UntagPolicy",
    ]
    resources = ["arn:${local.partition}:iam::${local.account}:policy/${local.name_prefix}-*"]
  }

  # A task definition names the two roles it runs under; nothing else may be
  # handed to any service.
  statement {
    sid       = "PassTaskRolesToTheRuntimeOnly"
    actions   = ["iam:PassRole"]
    resources = ["arn:${local.partition}:iam::${local.account}:role/${local.name_prefix}-*"]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "read" {
  name   = "read"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.read.json
}

resource "aws_iam_role_policy" "graph_platform" {
  name   = "graph-platform"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.graph_platform.json
}

resource "aws_iam_role_policy" "graph_data" {
  name   = "graph-data"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.graph_data.json
}

# What the deploy workflow itself needs: the state, the registry, and the
# portal build kept by commit.

data "aws_iam_policy_document" "pipeline" {
  statement {
    sid       = "ListOnlyThisEnvironmentsKeys"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.state_key_prefix}/*", "builds/portal/*", "plans/${var.state_key_prefix}/*"]
    }
  }

  # The state and its lock object, which `use_lockfile` puts beside it.
  statement {
    sid       = "OwnState"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.state_bucket_arn}/${var.state_key_prefix}/*"]
  }

  statement {
    sid       = "SavedPlans"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.state_bucket_arn}/plans/${var.state_key_prefix}/*"]
  }

  statement {
    sid = "PortalBuildsByCommit"
    actions = concat(
      ["s3:GetObject"],
      var.write_portal_builds ? ["s3:PutObject", "s3:DeleteObject"] : [],
    )
    resources = ["${local.state_bucket_arn}/builds/portal/*"]
  }

  statement {
    sid       = "RegistryLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # Production promotes what staging already built, so it reads digests and
  # never writes one.
  statement {
    sid = "Images"
    actions = concat(
      [
        "ecr:BatchCheckLayerAvailability",
        "ecr:BatchGetImage",
        "ecr:DescribeImages",
        "ecr:GetDownloadUrlForLayer",
      ],
      var.push_images ? [
        "ecr:CompleteLayerUpload",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart",
      ] : [],
    )
    resources = local.image_repository_arns
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "pipeline"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.pipeline.json
}

# The fences. A deny beats every allow, here and in any policy added later.

data "aws_iam_policy_document" "fences" {
  # Every resource the graph makes carries the environment as a tag, so this
  # one statement keeps a staging credential out of production whatever the
  # allow side grows into. It matches only what is tagged as the other
  # environment, so a resource mid-creation, which has no tags yet, is
  # unaffected.
  statement {
    sid       = "NothingBelongingToTheOtherEnvironment"
    effect    = "Deny"
    actions   = ["*"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/tadas:environment"
      values   = [var.other_environment]
    }
  }

  statement {
    sid     = "NotTheOtherEnvironmentsState"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      "${local.state_bucket_arn}/${var.other_state_key_prefix}/*",
      "${local.state_bucket_arn}/plans/${var.other_state_key_prefix}/*",
    ]
  }

  # `shared` is applied by a person, never by a deploy run: the registry, the
  # state bucket itself, and the trust that makes any of this work.
  statement {
    sid    = "NotWhatSharedOwns"
    effect = "Deny"
    actions = [
      "ecr:CreateRepository",
      "ecr:DeleteLifecyclePolicy",
      "ecr:DeleteRepository",
      "ecr:DeleteRepositoryPolicy",
      "ecr:PutImageTagMutability",
      "ecr:PutLifecyclePolicy",
      "ecr:SetRepositoryPolicy",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "NotTheStateBucketItself"
    effect = "Deny"
    actions = [
      "s3:DeleteBucket",
      "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketVersioning",
      "s3:PutEncryptionConfiguration",
    ]
    resources = [local.state_bucket_arn]
  }

  # The role cannot widen itself, nor reach the roles of the other jobs, nor
  # the operators' roles and user, nor the trust that issues any of them, nor
  # mint a principal outside all of these.
  statement {
    sid     = "NoWideningOfTheDeployCredentials"
    effect  = "Deny"
    actions = ["iam:*"]
    resources = [
      "arn:${local.partition}:iam::${local.account}:role/tadas-deploy-*",
      "arn:${local.partition}:iam::${local.account}:role/tadas-plan-*",
      "arn:${local.partition}:iam::${local.account}:role/tadas-investigate-*",
      "arn:${local.partition}:iam::${local.account}:user/tadas-operators",
      "arn:${local.partition}:iam::${local.account}:policy/tadas-task-boundary-*",
    ]
  }

  statement {
    sid    = "NoNewPrincipalsAndNoNewTrust"
    effect = "Deny"
    actions = [
      "iam:AddClientIDToOpenIDConnectProvider",
      "iam:CreateAccessKey",
      "iam:CreateLoginProfile",
      "iam:CreateOpenIDConnectProvider",
      "iam:CreateSAMLProvider",
      "iam:CreateUser",
      "iam:DeleteOpenIDConnectProvider",
      "iam:RemoveClientIDFromOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint",
    ]
    resources = ["*"]
  }

  # Every role this role creates carries the task boundary, so a task role is
  # a ceiling below this one and a compromised deploy run cannot mint a role
  # wider than itself and pass it to a task.
  statement {
    sid       = "NoRoleWithoutTheTaskBoundary"
    effect    = "Deny"
    actions   = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"]
    resources = ["*"]

    condition {
      test     = "StringNotEquals"
      variable = "iam:PermissionsBoundary"
      values   = [var.task_boundary_policy_arn]
    }
  }

  statement {
    sid       = "NoRemovingTheTaskBoundary"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary"]
    resources = ["*"]
  }

  statement {
    sid       = "OnlyTheGraphsOwnPoliciesAreAttachable"
    effect    = "Deny"
    actions   = ["iam:AttachRolePolicy"]
    resources = ["*"]

    condition {
      test     = "ArnNotLike"
      variable = "iam:PolicyARN"
      values   = local.attachable_policy_arns
    }
  }

  # Production's allowed pattern is the whole zone, because its names sit at
  # the base domain; staging's names sit under it and are subtracted here.
  dynamic "statement" {
    for_each = length(var.denied_dns_record_patterns) > 0 ? [1] : []

    content {
      sid       = "NotTheOtherEnvironmentsRecordNames"
      effect    = "Deny"
      actions   = ["route53:ChangeResourceRecordSets"]
      resources = ["arn:${local.partition}:route53:::hostedzone/*"]

      condition {
        test     = "ForAnyValue:StringLike"
        variable = "route53:ChangeResourceRecordSetsNormalizedRecordNames"
        values   = var.denied_dns_record_patterns
      }
    }
  }
}

resource "aws_iam_role_policy" "fences" {
  name   = "fences"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.fences.json
}
