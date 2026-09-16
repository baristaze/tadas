variable "environment" {
  description = "Environment name."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets the instance may live in."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups on the instance; ingress comes from the app group."
  type        = list(string)
}

variable "engine_version" {
  description = "Postgres major version; ADR 0002 names 16."
  type        = string
  default     = "16"
}

variable "instance_class" {
  type = string
}

variable "allocated_storage" {
  description = "Storage in GiB; autoscales up to five times this."
  type        = number
  default     = 20
}

variable "multi_az" {
  type = bool
}

variable "deletion_protection" {
  description = "Also decides whether a destroy takes a final snapshot."
  type        = bool
}

variable "backup_retention_days" {
  type    = number
  default = 7
}
