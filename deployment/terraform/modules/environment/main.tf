# One environment, whole: the graph every environment instantiates, from the
# network to the two processes. An environment root is this module called once
# with its parameter set and its backend, so there is one place a resource is
# added and no copy to keep in step. Each application process is one instance
# of the service module. Production promotes the images staging already ran,
# by digest, behind an approval gate: the image variables are the digests the
# deploy workflows pass.
#
# The module takes the `aws.us_east_1` alias as well as the default provider:
# CloudFront reads certificates from that region only.

locals {
  # The environment every process reads, mirrored from .env.example. Every
  # backend is the hosted one, and TADAS_ENVIRONMENT makes the process refuse
  # anything else at boot.
  process_environment = {
    TADAS_ENVIRONMENT         = var.environment
    TADAS_CACHE_BACKEND       = "valkey"
    TADAS_TOPICS_BACKEND      = "valkey"
    TADAS_VALKEY_URL          = module.cache.url
    TADAS_BUCKETS_BACKEND     = "s3"
    TADAS_S3_BUCKET_PREFIX    = module.buckets.prefix
    TADAS_QUEUES_BACKEND      = "sqs"
    TADAS_SQS_QUEUE_PREFIX    = module.queue.prefix
    TADAS_SECRETS_BACKEND     = "aws"
    TADAS_SECRETS_NAME_PREFIX = module.secrets.application_prefix
    TADAS_AWS_REGION          = var.region
    TADAS_LOG_JSON            = "true"
    TADAS_DATABASE_POOL_SIZE  = tostring(var.database_pool_size)
    # Read by no code. A rotation (database_password_version raised) changes
    # the task definition through this line, so every service rolls and its
    # new tasks start with the new URL; without it the old tasks would keep
    # the old password until their next reconnect failed.
    TADAS_DATABASE_PASSWORD_VERSION = tostring(var.database_password_version)
  }

  # A serving process connects as the runtime login, and as the system login
  # for the system scope, each with a pool of its own. The master's and the
  # migration login's URLs reach the migrate task alone.
  process_secrets = {
    TADAS_DATABASE_URL        = module.secrets.database_url_secret_arn
    TADAS_DATABASE_SYSTEM_URL = module.secrets.database_system_url_secret_arn
    TADAS_SENTRY_DSN          = module.secrets.sentry_dsn_secret_arn
  }

  # The revision before this release injected the master's URL as
  # TADAS_DATABASE_URL. A rollout the circuit breaker rolls back starts that
  # revision again, so the serving tasks' execution roles keep reading it
  # until the release that ends the transition.
  rollback_secret_arns = [module.secrets.database_master_url_secret_arn]

  # A one-off task opens small pools: it runs one command, not requests.
  # deployment/cloud/README.md counts them in the connection budget.
  one_off_environment = merge(local.process_environment, {
    TADAS_DATABASE_POOL_SIZE = "2"
  })

  # The API's admission bounds follow its pool, as the settings' defaults
  # do (48 and 16 over 12): four reads in flight per connection, and a
  # third as many writes.
  admission_limit_reads  = 4 * var.database_pool_size
  admission_limit_writes = ceil(4 * var.database_pool_size / 3)

  process_policies = [
    module.queue.policy_arn,
    module.buckets.policy_arn,
    module.secrets.policy_arn,
  ]
}

module "network" {
  source = "../network"

  environment = var.environment
  cidr        = var.vpc_cidr
}

module "cluster" {
  source = "../cluster"

  environment = var.environment
}

# The master password exists for the run and nowhere else: the database and
# the secret both take it write-only. Raising database_password_version
# writes a new one to both.
ephemeral "random_password" "database" {
  length  = 32
  special = false
}

module "database" {
  source = "../database"

  master_password         = ephemeral.random_password.database.result
  master_password_version = var.database_password_version

  environment         = var.environment
  subnet_ids          = module.network.private_subnet_ids
  security_group_ids  = [module.network.database_security_group_id]
  instance_class      = var.database_instance_class
  multi_az            = var.database_multi_az
  deletion_protection = var.database_deletion_protection
  destroyable         = var.destroyable
}

module "cache" {
  source = "../cache"

  environment        = var.environment
  subnet_ids         = module.network.private_subnet_ids
  security_group_ids = [module.network.cache_security_group_id]
  node_type          = var.cache_node_type
  node_count         = var.cache_node_count
}

module "queue" {
  source = "../queue"

  environment = var.environment
  prefix      = "tadas-${var.environment}-"
  queues      = ["webhooks"] # tadas.infra.queues.Queues
}

module "buckets" {
  source = "../buckets"

  environment = var.environment
  prefix      = var.bucket_prefix
  buckets     = ["user-file-uploads", "exports"] # tadas.infra.buckets.Buckets
  destroyable = var.destroyable
}

module "secrets" {
  source = "../secrets"

  environment               = var.environment
  prefix                    = "tadas/${var.environment}/"
  database_password         = ephemeral.random_password.database.result
  database_password_version = var.database_password_version
  database_username         = module.database.username
  database_address          = module.database.address
  database_port             = module.database.port
  database_name             = module.database.db_name
  destroyable               = var.destroyable
}

# Two public names, each at the apex of a Route 53 zone of its own that the
# account's bootstrap root made and delegated from Cloudflare: the API at the
# load balancer, the portal at CloudFront. Each gets a DNS-validated
# certificate; the portal's is in us-east-1, the only region CloudFront reads
# certificates from.
data "aws_route53_zone" "api" {
  name = var.api_domain_name
}

data "aws_route53_zone" "app" {
  name = var.app_domain_name
}

module "api_certificate" {
  source = "../certificate"

  environment = var.environment
  domain_name = var.api_domain_name
  zone_id     = data.aws_route53_zone.api.zone_id
}

module "app_certificate" {
  source    = "../certificate"
  providers = { aws = aws.us_east_1 }

  environment = var.environment
  domain_name = var.app_domain_name
  zone_id     = data.aws_route53_zone.app.zone_id
}

module "load_balancer" {
  source = "../load_balancer"

  environment        = var.environment
  vpc_id             = module.network.vpc_id
  subnet_ids         = module.network.public_subnet_ids
  security_group_ids = [module.network.load_balancer_security_group_id]
  certificate_arn    = module.api_certificate.arn
}

module "portal" {
  source = "../portal"

  environment     = var.environment
  bucket_name     = "${var.bucket_prefix}-portal"
  domain_name     = var.app_domain_name
  certificate_arn = module.app_certificate.arn
  api_url         = "https://${var.api_domain_name}"
  sentry_dsn      = var.portal_sentry_dsn
  destroyable     = var.destroyable
}

module "domain_records" {
  source = "../domain_records"

  api_zone_id              = data.aws_route53_zone.api.zone_id
  app_zone_id              = data.aws_route53_zone.app.zone_id
  api_domain_name          = var.api_domain_name
  app_domain_name          = var.app_domain_name
  load_balancer_dns_name   = module.load_balancer.dns_name
  load_balancer_zone_id    = module.load_balancer.zone_id
  distribution_domain_name = module.portal.distribution_domain_name
  distribution_zone_id     = module.portal.distribution_zone_id
}

# The two one-off tasks, both on the API image. The migrate task is the one
# place the master's and the migration login's URLs are injected: it runs
# `ensure-logins` as the master (the three logins, their passwords from their
# URLs, the ownership moved to the migration login, the grants), then the
# migrations as the migration login. It holds the runtime and system URLs as
# well, since `ensure-logins` sets those logins' passwords from them.
module "migrate" {
  source = "../task"

  name        = "migrate"
  image       = var.api_image
  environment = var.environment
  command     = ["tadas-api", "migrate", "--all"]

  environment_variables = merge(local.one_off_environment, {
    TADAS_SERVICE_NAME = "migrate"
  })

  secrets = merge(local.process_secrets, {
    TADAS_DATABASE_MIGRATION_URL = module.secrets.database_migration_url_secret_arn
    TADAS_DATABASE_MASTER_URL    = module.secrets.database_master_url_secret_arn
  })
}

# The grant task runs `tadas-api grant-operator`: a person's operator
# permission, or a minted token written to its secret. It connects as the
# runtime and system logins, and its role holds one write, PutSecretValue on
# the two token secrets. The grant workflow starts it with its command as an
# override; the definition's own command only prints the usage.
module "grant" {
  source = "../task"

  name        = "grant"
  image       = var.api_image
  environment = var.environment
  command     = ["tadas-api", "grant-operator", "--help"]
  policy_arns = [module.secrets.operator_tokens_policy_arn]

  environment_variables = merge(local.one_off_environment, {
    TADAS_SERVICE_NAME = "grant"
  })

  secrets = local.process_secrets
}

# A stateless service rolls with one extra replica (the module's defaults).
# Before it rolls, the migrate task runs on the new image, once per step; a
# migration is compatible with the release before it (expand and contract),
# so the old tasks serve the new schema until the roll ends.
module "api" {
  source = "../service"

  name               = "api"
  image              = var.api_image
  environment        = var.environment
  cluster_arn        = module.cluster.arn
  subnet_ids         = module.network.private_subnet_ids
  security_group_ids = [module.network.app_security_group_id]
  desired_count      = var.api_desired_count
  cpu                = var.api_cpu
  memory             = var.api_memory
  port               = 8000
  metrics_port       = 8000
  target_group_arn   = module.load_balancer.target_group_arn
  policy_arns        = local.process_policies

  rollback_secret_arns = local.rollback_secret_arns

  secrets = merge(local.process_secrets, {
    TADAS_TOTP_ENCRYPTION_KEY = module.secrets.totp_encryption_key_secret_arn
  })

  environment_variables = merge(local.process_environment, {
    TADAS_SERVICE_NAME           = "api"
    TADAS_ADMISSION_LIMIT_READS  = tostring(local.admission_limit_reads)
    TADAS_ADMISSION_LIMIT_WRITES = tostring(local.admission_limit_writes)
    TADAS_HOST                   = "0.0.0.0"
    TADAS_PORT                   = "8000"
    TADAS_CORS_ORIGINS           = jsonencode(concat(["https://${var.app_domain_name}"], var.cors_origins))
    # The edge serves the API and liveness; the interactive docs are local.
    TADAS_INTERACTIVE_DOCS = "false"
    # The load balancer lives in the VPC, so its X-Forwarded-For names the client.
    TADAS_TRUSTED_PROXIES = jsonencode([var.vpc_cidr])
  })

  health_check_command = [
    "CMD-SHELL",
    "python -c \"import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status == 200 else 1)\"",
  ]

  pre_rollout = {
    task_definition_arn = module.migrate.task_definition_arn
    container           = module.migrate.container_name
    commands = [
      ["tadas-api", "migrate", "ensure-logins"],
      ["tadas-api", "migrate", "--all"],
    ]
  }

  autoscaling = {
    enabled    = var.autoscaling_enabled && var.api_autoscaling.enabled
    max        = var.api_autoscaling.max
    target_cpu = var.api_autoscaling.target_cpu
  }
}

# A worker holds leases, so a rollout never runs more workers than desired:
# at most 100% during a deployment, and the old replica stops before its
# replacement starts. The stop timeout covers the drain. It rolls after the
# API's migration ran.
module "maintenance" {
  source = "../service"

  name               = "maintenance"
  image              = var.maintenance_image
  environment        = var.environment
  cluster_arn        = module.cluster.arn
  subnet_ids         = module.network.private_subnet_ids
  security_group_ids = [module.network.app_security_group_id]
  desired_count      = var.maintenance_desired_count
  cpu                = var.maintenance_cpu
  memory             = var.maintenance_memory
  metrics_port       = 9464
  policy_arns        = local.process_policies
  secrets            = local.process_secrets

  rollback_secret_arns = local.rollback_secret_arns

  environment_variables = merge(local.process_environment, {
    TADAS_SERVICE_NAME = "maintenance"
  })

  # The serving process answers /healthz on its metrics port from its
  # loop's last beat, held in memory; the probe boots nothing.
  health_check_command = [
    "CMD-SHELL",
    "python -c \"import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9464/healthz').status == 200 else 1)\"",
  ]

  deployment_maximum_percent         = 100
  deployment_minimum_healthy_percent = floor(100 * (var.maintenance_desired_count - 1) / var.maintenance_desired_count)
  stop_timeout_seconds               = 120
  rollout_after                      = module.api.rollout_gate

  autoscaling = {
    enabled    = var.autoscaling_enabled && var.maintenance_autoscaling.enabled
    max        = var.maintenance_autoscaling.max
    target_cpu = var.maintenance_autoscaling.target_cpu
  }
}

# What an operator reads. The dashboard is the cloud twin of the local
# Grafana one, by panel title; the alarms are the default set, to one topic.

module "dashboard" {
  source = "../dashboard"

  environment         = var.environment
  cluster_name        = module.cluster.name
  service_names       = [module.api.service_name, module.maintenance.service_name]
  database_identifier = module.database.identifier
  cache_node_ids      = module.cache.member_clusters
  queue_names         = module.queue.queue_names
}

module "alarms" {
  source = "../alarms"

  environment              = var.environment
  alarm_email              = var.alarm_email
  load_balancer_arn_suffix = module.load_balancer.arn_suffix
  target_group_arn_suffix  = module.load_balancer.target_group_arn_suffix
  database_identifier      = module.database.identifier
  cluster_name             = module.cluster.name
  service_names            = [module.api.service_name, module.maintenance.service_name]
}
