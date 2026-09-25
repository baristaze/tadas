variable "environment" {
  description = "Environment name; in every alarm's name and on the topic's tags."
  type        = string
}

variable "alarm_email" {
  description = "The address every alarm is sent to. Others subscribe by hand."
  type        = string
}

variable "load_balancer_arn_suffix" {
  description = "The load balancer's ARN suffix (app/<name>/<id>), the dimension its metrics carry."
  type        = string
}

variable "target_group_arn_suffix" {
  description = "The API target group's ARN suffix (targetgroup/<name>/<id>)."
  type        = string
}

variable "database_identifier" {
  description = "The database instance identifier, e.g. tadas-staging."
  type        = string
}

variable "cluster_name" {
  description = "The container cluster the services run on."
  type        = string
}

variable "api_log_group_name" {
  description = "The API's log group; a read's latency is read from its access lines there."
  type        = string
}

variable "service_names" {
  description = "One tasks-below-desired alarm per service named here."
  type        = list(string)
}

# Thresholds. Numbers, not shape: an environment passes another number.

variable "period_seconds" {
  description = "How long one evaluation period is."
  type        = number
  default     = 60
}

variable "evaluation_periods" {
  description = "How many periods in a row must breach before the alarm fires."
  type        = number
  default     = 3
}

variable "tasks_below_desired_periods" {
  description = "How many periods in a row a service must run fewer tasks than it wants before its alarm fires: longer than a deploy leaves the worker at none (its 120s drain plus a start)."
  type        = number
  default     = 6
}

variable "http_5xx_ratio_percent" {
  description = "5xx answers as a percentage of requests, above which the edge alarm fires."
  type        = number
  default     = 5
}

variable "http_p95_latency_seconds" {
  description = "The load balancer's p95 target response time, in seconds, above which the latency alarm fires."
  type        = number
  default     = 1
}

variable "database_cpu_percent" {
  type    = number
  default = 80
}

variable "database_free_storage_bytes" {
  description = "Free storage below which the database alarm fires; 2 GiB by default."
  type        = number
  default     = 2147483648
}

variable "read_latency_p95_seconds" {
  description = "One latency alarm per read named here: the GET route's template, and the p95 in seconds above which it fires."
  type        = map(number)
  default = {
    "/v1/billing" = 1
  }
}
