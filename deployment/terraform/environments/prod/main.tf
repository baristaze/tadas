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
}
