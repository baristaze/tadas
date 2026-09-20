variable "name" {
  description = "Service name, as it appears in the service catalog; also the container name."
  type        = string
}

variable "image" {
  description = "Image reference by digest; production promotes what staging already ran."
  type        = string
}

variable "environment" {
  description = "Environment name, passed to the process as TADAS_ENVIRONMENT."
  type        = string
}

variable "cluster_arn" {
  type = string
}

variable "subnet_ids" {
  description = "Private subnets tasks run in."
  type        = list(string)
}

variable "security_group_ids" {
  type = list(string)
}

variable "desired_count" {
  description = "Number of replicas."
  type        = number
  default     = 1
}

variable "cpu" {
  description = "CPU units per task."
  type        = number
  default     = 256
}

variable "memory" {
  description = "Memory in MiB per task."
  type        = number
  default     = 512
}

variable "port" {
  description = "Container port; null for a worker with no network surface."
  type        = number
  default     = null
}

variable "command" {
  description = "Overrides the image's CMD; null keeps it."
  type        = list(string)
  default     = null
}

variable "environment_variables" {
  description = "Plain environment for the process, every key under the TADAS_ prefix."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Environment injected from Secrets Manager: variable name to secret ARN."
  type        = map(string)
  default     = {}
}

variable "policy_arns" {
  description = "Policies the task role gets: the queues, buckets, and secrets the process uses."
  type        = list(string)
  default     = []
}

variable "target_group_arn" {
  description = "Registers the container with a load balancer; null for a worker."
  type        = string
  default     = null
}

variable "health_check_command" {
  description = "The container health check, in the ECS command form; null disables it."
  type        = list(string)
  default     = null
}

variable "deployment_maximum_percent" {
  description = "Replicas during a rollout, as a percentage of desired. A worker holds leases, so a worker instance passes 100: never more than desired."
  type        = number
  default     = 200
}

variable "deployment_minimum_healthy_percent" {
  description = "Replicas that must stay running during a rollout, as a percentage of desired."
  type        = number
  default     = 100
}

variable "stop_timeout_seconds" {
  description = "Time between SIGTERM and SIGKILL; a worker needs enough to return its leases."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "metrics_port" {
  description = "Port the process serves /metrics on, on localhost; the collector sidecar scrapes it."
  type        = number
}

variable "collector_image" {
  description = "The AWS Distro for OpenTelemetry collector image the sidecar runs."
  type        = string
  default     = "public.ecr.aws/aws-observability/aws-otel-collector:v0.50.0"
}

variable "pre_rollout_command" {
  description = "A command run as a one-off task on every new task definition before the service rolls, e.g. the migration; null runs nothing."
  type        = list(string)
  default     = null
}

variable "rollout_after" {
  description = "A value the rollout waits for: another instance's rollout_gate output, so a worker rolls only after the API's migration ran."
  type        = string
  default     = ""
}
