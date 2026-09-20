variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "github_repository" {
  description = "The repository whose deploy workflow may assume the deploy role, as owner/name."
  type        = string
}

variable "images" {
  description = "One registry per image under deployment/docker/."
  type        = list(string)
  default     = ["tadas-api", "tadas-maintenance"]
}

variable "state_bucket" {
  description = "The bucket every root's state lives in. Created here with local state first, then adopted with `terraform init -migrate-state`."
  type        = string
}

variable "dns_zone_name" {
  description = "The Route 53 hosted zone both environments' public names live in, e.g. tadas.fyi. Each deploy role may change only the record names its own environment owns."
  type        = string
}
