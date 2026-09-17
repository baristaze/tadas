variable "environment" {
  description = "Environment name; written into the portal's runtime config."
  type        = string
}

variable "bucket_name" {
  description = "The private bucket the built portal is uploaded to."
  type        = string
}

variable "api_origin_domain" {
  description = "Where CloudFront forwards /v1/*: the load balancer's DNS name, or a name on its certificate."
  type        = string
}

variable "api_origin_https" {
  description = "Forward to the API over HTTPS. Needs api_origin_domain to be a name the load balancer's certificate covers."
  type        = bool
}

variable "aliases" {
  description = "Custom domain names for the portal; empty serves it on the cloudfront.net name."
  type        = list(string)
  default     = []
}

variable "certificate_arn" {
  description = "An ACM certificate in us-east-1 covering the aliases; null uses CloudFront's own certificate."
  type        = string
  default     = null
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
