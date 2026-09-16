variable "environment" {
  description = "Environment name."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  description = "Public subnets."
  type        = list(string)
}

variable "security_group_ids" {
  type = list(string)
}

variable "target_port" {
  description = "The port the API container listens on."
  type        = number
  default     = 8000
}

variable "health_check_path" {
  type    = string
  default = "/healthz"
}

variable "certificate_arn" {
  description = "An ACM certificate for HTTPS. Null serves plain HTTP, which is only acceptable before a domain exists."
  type        = string
  default     = null
}
