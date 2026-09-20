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
  description = <<-EOT
    What the target group polls to decide whether to send a target traffic,
    which is readiness and not liveness: /readyz answers whether this process
    can serve a request right now, under a deadline of its own, and a timeout
    is a negative answer. The container healthcheck keeps /healthz, which
    decides whether the process is alive and should be restarted.
  EOT
  type        = string
  default     = "/readyz"
}

variable "certificate_arn" {
  description = "The validated ACM certificate for the API's domain name."
  type        = string
}
