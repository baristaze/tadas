# The root's own inputs: the region and the environment name the provider
# tags with, and what the deploy workflow passes per run. Everything that
# makes this environment itself is in the module call in main.tf.

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, passed to every process as TADAS_ENVIRONMENT and tagged on every resource."
  type        = string
  default     = "production"
}

variable "api_image" {
  description = "The API image by digest (<registry>/tadas-api@sha256:...); the deploy workflows pass it."
  type        = string
}

variable "maintenance_image" {
  description = "The maintenance worker image by digest; the deploy workflows pass it."
  type        = string
}

variable "dns_zone_name" {
  description = "The Route 53 hosted zone both public names live in, e.g. tadas.fyi."
  type        = string
}

variable "api_domain_name" {
  description = "The API's public name, a name inside dns_zone_name."
  type        = string
}

variable "app_domain_name" {
  description = "The portal's public name, a name inside dns_zone_name."
  type        = string
}

variable "cors_origins" {
  description = "Browser origins the API accepts besides the portal's, which is always allowed."
  type        = list(string)
  default     = []
}

variable "portal_sentry_dsn" {
  description = "The portal's error-reporting DSN (public by design); empty turns browser reporting off."
  type        = string
  default     = ""
}

variable "alarm_email" {
  description = "The address the environment's alarm topic delivers to; the deploy workflows pass the ALARM_EMAIL repository variable."
  type        = string
}

variable "destroyable" {
  description = "Never set by a deploy. `scripts/cloud_nuke.sh` passes true on its apply before the destroy: buckets empty, the database skips its final snapshot and drops its deletion protection."
  type        = bool
  default     = false
}
