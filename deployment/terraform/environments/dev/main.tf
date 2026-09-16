# The module graph is identical in every environment; only variables
# differ. Each application process is one instance of the service module.
# Production promotes the images dev already ran, by digest, behind an
# approval gate: the image variables are the digests deploy.yml passes.

locals {
  # The environment every process reads, mirrored from .env.example. Every
  # backend is the hosted one, and TADAS_ENVIRONMENT makes the process refuse
  # anything else at boot.
  process_environment = {
    TADAS_ENVIRONMENT         = var.environment
    TADAS_CACHE_BACKEND       = "redis"
    TADAS_TOPICS_BACKEND      = "redis"
    TADAS_REDIS_URL           = module.cache.url
    TADAS_BUCKETS_BACKEND     = "s3"
    TADAS_S3_BUCKET_PREFIX    = module.buckets.prefix
    TADAS_QUEUES_BACKEND      = "sqs"
    TADAS_SQS_QUEUE_PREFIX    = module.queue.prefix
    TADAS_SECRETS_BACKEND     = "aws"
    TADAS_SECRETS_NAME_PREFIX = module.secrets.application_prefix
    TADAS_AWS_REGION          = var.region
    TADAS_LOG_JSON            = "true"
  }

  process_secrets = {
    TADAS_DATABASE_URL = module.secrets.database_url_secret_arn
  }

  process_policies = [
    module.queue.policy_arn,
    module.buckets.policy_arn,
    module.secrets.policy_arn,
  ]
}

module "network" {
  source = "../../modules/network"

  environment = var.environment
  cidr        = var.vpc_cidr
}

module "cluster" {
  source = "../../modules/cluster"

  environment = var.environment
}

module "database" {
  source = "../../modules/database"

  environment         = var.environment
  subnet_ids          = module.network.private_subnet_ids
  security_group_ids  = [module.network.database_security_group_id]
  instance_class      = var.database_instance_class
  multi_az            = var.database_multi_az
  deletion_protection = var.database_deletion_protection
}

module "cache" {
  source = "../../modules/cache"

  environment        = var.environment
  subnet_ids         = module.network.private_subnet_ids
  security_group_ids = [module.network.cache_security_group_id]
  node_type          = var.cache_node_type
  node_count         = var.cache_node_count
}

module "queue" {
  source = "../../modules/queue"

  environment = var.environment
  prefix      = "tadas-${var.environment}-"
  queues      = ["webhooks"] # tadas.infra.queues.Queues
}

module "buckets" {
  source = "../../modules/buckets"

  environment = var.environment
  prefix      = var.bucket_prefix
  buckets     = ["user-file-uploads", "exports"] # tadas.infra.buckets.Buckets
}

module "secrets" {
  source = "../../modules/secrets"

  environment  = var.environment
  prefix       = "tadas/${var.environment}/"
  database_url = module.database.url
}

module "load_balancer" {
  source = "../../modules/load_balancer"

  environment        = var.environment
  vpc_id             = module.network.vpc_id
  subnet_ids         = module.network.public_subnet_ids
  security_group_ids = [module.network.load_balancer_security_group_id]
  certificate_arn    = var.certificate_arn
}

# A stateless service rolls with one extra replica (the module's defaults).
module "api" {
  source = "../../modules/service"

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
  target_group_arn   = module.load_balancer.target_group_arn
  policy_arns        = local.process_policies
  secrets            = local.process_secrets

  environment_variables = merge(local.process_environment, {
    TADAS_SERVICE_NAME = "api"
    TADAS_HOST         = "0.0.0.0"
    TADAS_PORT         = "8000"
    TADAS_CORS_ORIGINS = jsonencode(var.cors_origins)
  })

  health_check_command = [
    "CMD-SHELL",
    "python -c \"import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status == 200 else 1)\"",
  ]
}

# A worker holds leases, so a rollout never runs more workers than desired:
# at most 100% during a deployment, and the old replica stops before its
# replacement starts. The stop timeout covers the drain.
module "maintenance" {
  source = "../../modules/service"

  name               = "maintenance"
  image              = var.maintenance_image
  environment        = var.environment
  cluster_arn        = module.cluster.arn
  subnet_ids         = module.network.private_subnet_ids
  security_group_ids = [module.network.app_security_group_id]
  desired_count      = var.maintenance_desired_count
  cpu                = var.maintenance_cpu
  memory             = var.maintenance_memory
  policy_arns        = local.process_policies
  secrets            = local.process_secrets

  environment_variables = merge(local.process_environment, {
    TADAS_SERVICE_NAME = "maintenance"
  })

  # The serving process is PID 1 (the entrypoint execs it), so its default
  # worker id is maintenance-<hostname>-1 unless TADAS_WORKER_ID says otherwise.
  health_check_command = [
    "CMD-SHELL",
    "tadas-maintenance health --worker-id \"$${TADAS_WORKER_ID:-maintenance-$(cat /etc/hostname)-1}\"",
  ]

  deployment_maximum_percent         = 100
  deployment_minimum_healthy_percent = floor(100 * (var.maintenance_desired_count - 1) / var.maintenance_desired_count)
  stop_timeout_seconds               = 120
}
