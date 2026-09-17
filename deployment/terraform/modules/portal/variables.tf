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
  description = "The portal's error-reporting DSN; browser DSNs are public by design. Empty turns reporting off."
  type        = string
  default     = ""
}

variable "price_class" {
  description = "Which edge locations serve the portal."
  type        = string
  default     = "PriceClass_100"
}
