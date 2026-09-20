variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, passed to every process as TADAS_ENVIRONMENT. The set is the one tadas.infra.impl.settings knows: the process refuses any other."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "environment must be one of dev, staging, production; a process refuses any other name."
  }
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
  description = "The Route 53 hosted zone both public names live in, e.g. tadas.fyi. Terraform validates the certificates and writes the records there."
  type        = string
}

variable "api_domain_name" {
  description = "The API's public name, e.g. api.tadas.fyi, or api.staging.tadas.fyi for staging."
  type        = string

  validation {
    condition     = endswith(var.api_domain_name, ".${var.dns_zone_name}")
    error_message = "api_domain_name must be a name inside dns_zone_name."
  }
}

variable "app_domain_name" {
  description = "The portal's public name, e.g. app.tadas.fyi, or app.staging.tadas.fyi for staging."
  type        = string

  validation {
    condition     = endswith(var.app_domain_name, ".${var.dns_zone_name}")
    error_message = "app_domain_name must be a name inside dns_zone_name."
  }
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

# Scale. Everything below is what differs from staging: the module graph does not.

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "bucket_prefix" {
  description = "Bucket names are global; the prefix carries the environment."
  type        = string
  default     = "tadas-production"
}

variable "database_instance_class" {
  type    = string
  default = "db.m6g.large"
}

variable "database_multi_az" {
  type    = bool
  default = true
}

variable "database_deletion_protection" {
  type    = bool
  default = true
}

variable "cache_node_type" {
  type    = string
  default = "cache.m6g.large"
}

variable "cache_node_count" {
  type    = number
  default = 2
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 1024
}

variable "maintenance_desired_count" {
  type    = number
  default = 2
}

variable "maintenance_cpu" {
  type    = number
  default = 512
}

variable "maintenance_memory" {
  type    = number
  default = 1024
}
