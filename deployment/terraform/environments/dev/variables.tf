variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, passed to every process as TADAS_ENVIRONMENT. The set is the one tadas.infra.impl.settings knows: the process refuses any other."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "environment must be one of dev, staging, production; a process refuses any other name."
  }
}

variable "api_image" {
  description = "The API image by digest (<registry>/tadas-api@sha256:...); deploy.yml passes it."
  type        = string
}

variable "maintenance_image" {
  description = "The maintenance worker image by digest; deploy.yml passes it."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate for the load balancer; null until a domain exists."
  type        = string
  default     = null
}

variable "api_domain_name" {
  description = "A name on the load balancer's certificate, pointing at it; CloudFront forwards /v1/* there over HTTPS. Required once certificate_arn is set."
  type        = string
  default     = null

  validation {
    condition     = var.certificate_arn == null || var.api_domain_name != null
    error_message = "Set api_domain_name when certificate_arn is set: CloudFront can only reach an HTTPS load balancer by a name its certificate covers."
  }
}

variable "cors_origins" {
  description = "Other browser origins the API accepts. The portal needs none: CloudFront serves it and the API on one origin."
  type        = list(string)
  default     = []
}

variable "portal_aliases" {
  description = "Custom domain names for the portal; empty serves it on its cloudfront.net name."
  type        = list(string)
  default     = []
}

variable "portal_certificate_arn" {
  description = "An ACM certificate in us-east-1 covering portal_aliases."
  type        = string
  default     = null
}

variable "portal_sentry_dsn" {
  description = "The portal's error-reporting DSN (public by design); empty turns browser reporting off."
  type        = string
  default     = ""
}

# Scale. Everything below is what makes this environment the smaller one.

variable "vpc_cidr" {
  type    = string
  default = "10.10.0.0/16"
}

variable "bucket_prefix" {
  description = "Bucket names are global; the prefix carries the environment."
  type        = string
  default     = "tadas-dev"
}

variable "database_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "database_multi_az" {
  type    = bool
  default = false
}

variable "database_deletion_protection" {
  type    = bool
  default = false
}

variable "cache_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "cache_node_count" {
  type    = number
  default = 1
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "api_cpu" {
  type    = number
  default = 256
}

variable "api_memory" {
  type    = number
  default = 512
}

variable "maintenance_desired_count" {
  type    = number
  default = 1
}

variable "maintenance_cpu" {
  type    = number
  default = 256
}

variable "maintenance_memory" {
  type    = number
  default = 512
}
