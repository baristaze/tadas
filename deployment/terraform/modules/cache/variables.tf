variable "environment" {
  description = "Environment name."
  type        = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_ids" {
  type = list(string)
}

variable "engine_version" {
  type    = string
  default = "7.1"
}

variable "node_type" {
  type = string
}

variable "node_count" {
  description = "One primary plus replicas; more than one enables automatic failover."
  type        = number
}
