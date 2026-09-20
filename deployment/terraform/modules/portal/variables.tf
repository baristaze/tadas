variable "environment" {
  description = "Environment name; written into the portal's runtime config."
  type        = string
}

variable "bucket_name" {
  description = "The private bucket the built portal is uploaded to."
  type        = string
}

variable "domain_name" {
  description = "The portal's domain name, e.g. app.tadas.fyi."
  type        = string
}

variable "certificate_arn" {
  description = "A validated ACM certificate in us-east-1 for domain_name."
  type        = string
}

variable "api_url" {
  description = "The API's base URL the portal calls, e.g. https://api.tadas.fyi."
  type        = string
}

variable "sentry_dsn" {
  description = "The portal's error-reporting DSN; browser DSNs are public by design. Empty turns reporting off. Its origin is the one address beside the API the Content-Security-Policy lets the page reach."
  type        = string
  default     = ""

  validation {
    condition     = var.sentry_dsn == "" || can(regex("^(https?://)[^@/]+@([^/]+)", var.sentry_dsn))
    error_message = "sentry_dsn is empty or scheme://key@host/project."
  }
}

variable "price_class" {
  description = "Which edge locations serve the portal."
  type        = string
  default     = "PriceClass_100"
}

variable "destroyable" {
  description = "True on the nuke's way down only: a destroy then empties the bucket."
  type        = bool
  default     = false
}
