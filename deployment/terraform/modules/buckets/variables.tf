variable "environment" {
  description = "Environment name."
  type        = string
}

variable "prefix" {
  description = "Bucket name prefix; the process reads it as TADAS_S3_BUCKET_PREFIX. Bucket names are global, so it carries the environment."
  type        = string
}

variable "buckets" {
  description = "One entry per member of tadas.infra.buckets.Buckets."
  type        = list(string)
}

variable "destroyable" {
  description = "True on the nuke's way down only: a destroy then empties the buckets."
  type        = bool
}
