variable "environment" {
  description = "The environment this role reads, and the only one it may see."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "other_environment" {
  description = "The environment this role must never reach. Resources tagged with it are denied outright."
  type        = string
}

variable "state_bucket" {
  description = "The bucket every root's state lives in."
  type        = string
}

variable "state_key_prefix" {
  description = "This environment's prefix inside the state bucket, without a trailing slash, e.g. environments/staging."
  type        = string
}

variable "other_state_key_prefix" {
  description = "The other environment's prefix, denied outright."
  type        = string
}

variable "operators_user_arn" {
  description = "The IAM user the agents run as; its only permission is to assume the investigate roles."
  type        = string
}

variable "operator_principal_arns" {
  description = "Principals besides the operators user that may assume this role: a person's user, or an Identity Center permission set's role."
  type        = list(string)
  default     = []
}
