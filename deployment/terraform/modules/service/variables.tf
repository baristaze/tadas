variable "name" {
  description = "Service name, as it appears in the service catalog."
  type        = string
}

variable "image" {
  description = "Image reference by digest; production promotes what dev already ran."
  type        = string
}

variable "environment" {
  description = "Environment name, passed to the process as TADAS_ENVIRONMENT."
  type        = string
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
