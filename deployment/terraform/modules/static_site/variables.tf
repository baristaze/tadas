variable "name" {
  description = "What the site is, in its resources' names and descriptions: portal or site."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.name))
    error_message = "name is lowercase letters, digits, and dashes."
  }
}

variable "environment" {
  description = "Environment name, in resource names and tags."
  type        = string
}

variable "bucket_name" {
  description = "The private bucket the built site is uploaded to."
  type        = string
}

variable "domain_name" {
  description = "The site's domain name, e.g. app.tadas.fyi or www.tadas.fyi."
  type        = string
}

variable "certificate_arn" {
  description = "A validated ACM certificate in us-east-1 for domain_name."
  type        = string
}

variable "api_url" {
  description = "The API's base URL the page calls, e.g. https://api.tadas.fyi; the Content-Security-Policy lets the page reach it over HTTPS and the websocket. Empty for a page that calls no API."
  type        = string
  default     = ""
}

variable "sentry_dsn" {
  description = "The page's error-reporting DSN; browser DSNs are public by design. Empty turns reporting off. Its origin is the one address beside the API the Content-Security-Policy lets the page reach."
  type        = string
  default     = ""

  validation {
    condition     = var.sentry_dsn == "" || can(regex("^(https?://)[^@/]+@([^/]+)", var.sentry_dsn))
    error_message = "sentry_dsn is empty or scheme://key@host/project."
  }
}

variable "runtime_config" {
  description = "Written as /config.json, which the page reads before it renders. Empty writes no file."
  type        = map(string)
  default     = {}
}

variable "client_routes" {
  description = "True for a single-page app: a path without a file extension gets index.html."
  type        = bool
  default     = false
}

variable "not_found_page" {
  description = "The page a missing path gets, with a 404, e.g. /404.html. Empty leaves CloudFront's own answer."
  type        = string
  default     = ""

  validation {
    condition     = var.not_found_page == "" || startswith(var.not_found_page, "/")
    error_message = "not_found_page is empty or a path from the root, e.g. /404.html."
  }
}

variable "price_class" {
  description = "Which edge locations serve the site."
  type        = string
  default     = "PriceClass_100"
}

variable "destroyable" {
  description = "True on the nuke's way down only: a destroy then empties the bucket."
  type        = bool
  default     = false
}
