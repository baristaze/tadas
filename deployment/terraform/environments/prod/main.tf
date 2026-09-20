# Production: the `release` branch's environment. The graph is
# ../../modules/environment, the same one staging runs; this call is the
# parameter set that makes it production. Nothing here differs from staging
# but the numbers, the names, and the two protections a production database
# carries.

module "environment" {
  source    = "../../modules/environment"
  providers = { aws = aws, aws.us_east_1 = aws.us_east_1 }

  region      = var.region
  environment = var.environment

  # What the deploy workflow passes per run.
  api_image         = var.api_image
  maintenance_image = var.maintenance_image
  dns_zone_name     = var.dns_zone_name
  api_domain_name   = var.api_domain_name
  app_domain_name   = var.app_domain_name
  cors_origins      = var.cors_origins
  portal_sentry_dsn = var.portal_sentry_dsn

  # Scale. Everything below is what differs from staging: the graph does not.
  vpc_cidr                     = "10.20.0.0/16"
  bucket_prefix                = "tadas-production"
  database_instance_class      = "db.m6g.large"
  database_multi_az            = true
  database_deletion_protection = true
  cache_node_type              = "cache.m6g.large"
  cache_node_count             = 2
  api_desired_count            = 2
  api_cpu                      = 512
  api_memory                   = 1024
  maintenance_desired_count    = 2
  maintenance_cpu              = 512
  maintenance_memory           = 1024

  # Operations. `autoscaling_enabled` is the one flip: every lever below it
  # is on, so true scales the whole environment, and the flip is a pull
  # request a person reads. Off by default because an unattended scale-out
  # is a bill nobody approved. Each lever's floor is the desired count above.
  alarm_email             = var.alarm_email
  autoscaling_enabled     = false
  api_autoscaling         = { max = 6 }
  maintenance_autoscaling = { max = 2 }
  destroyable             = var.destroyable
}
