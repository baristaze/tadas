# Staging: the smaller environment, and `main`. The graph is
# ../../modules/environment; this call is the parameter set that makes it
# staging. A new environment is another root like this one, never a copy of
# the graph.

module "environment" {
  source    = "../../modules/environment"
  providers = { aws = aws, aws.us_east_1 = aws.us_east_1 }

  region      = var.region
  environment = var.environment

  # What the deploy workflow passes per run.
  api_image         = var.api_image
  maintenance_image = var.maintenance_image
  api_domain_name   = var.api_domain_name
  app_domain_name   = var.app_domain_name
  cors_origins      = var.cors_origins
  # The WorkOS application of this environment's WorkOS environment. A
  # client id is public; the environment's API key is its secret.
  workos_client_id  = "client_01M3640D8WBF9KC0P89YW4E72N"
  portal_sentry_dsn = var.portal_sentry_dsn

  # The payment processor's account, the Tadas sandbox: test mode, no real money. The process refuses a key
  # whose mode is not this environment's.
  stripe_account_id = "acct_1UIfVX45a2t9JoiY"

  # Scale: size XS, the demo posture (deployment/cloud/README.md prices
  # every size). Everything below is what makes this environment the smaller
  # one. The pool is sized to the instance at the autoscaling ceilings, so
  # the flip below is safe: a db.t4g.micro takes about 80 connections, and
  # (2 x 2 API + 1 worker) x 2 pools x 6 + 8 for the one-off tasks is 68.
  vpc_cidr                     = "10.10.0.0/16"
  bucket_prefix                = "tadas-staging"
  database_instance_class      = "db.t4g.micro"
  database_multi_az            = false
  database_deletion_protection = false
  database_pool_size           = 6
  cache_node_type              = "cache.t4g.micro"
  cache_node_count             = 1
  api_desired_count            = 1
  api_cpu                      = 256
  api_memory                   = 512
  maintenance_desired_count    = 1
  maintenance_cpu              = 256
  maintenance_memory           = 512
  slack_cpu                    = 256
  slack_memory                 = 512

  # Operations. `autoscaling_enabled` is the one flip: every lever below it
  # is on, so true scales the whole environment, and the flip is a pull
  # request a person reads. Off by default because an unattended scale-out
  # is a bill nobody approved. Each lever's floor is the desired count above.
  alarm_email             = var.alarm_email
  autoscaling_enabled     = false
  api_autoscaling         = { max = 2 }
  maintenance_autoscaling = { max = 1 }
  destroyable             = var.destroyable
}
