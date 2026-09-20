variable "environment" {
  description = "The environment this role applies, and the only one it may touch."
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

variable "github_repository" {
  description = "owner/name of the repository whose jobs may assume this role."
  type        = string
}

variable "github_environment" {
  description = "The GitHub environment a job must declare to assume this role. The subject condition names it, so a job without it presents its branch instead and is refused."
  type        = string
}

variable "github_ref" {
  description = "The only ref a job assuming this role may run on, e.g. refs/heads/main or refs/heads/release."
  type        = string
}

variable "oidc_provider_arn" {
  description = "The GitHub OIDC provider in this account."
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

variable "image_repositories" {
  description = "The registry repositories this role may read, and push to when push_images is true."
  type        = list(string)
}

variable "push_images" {
  description = "True for the environment that builds. Production promotes digests, so it only reads."
  type        = bool
}

variable "write_portal_builds" {
  description = "True for the environment that keeps the portal build by commit; the other one reads it."
  type        = bool
}

variable "dns_zone_name" {
  description = "The hosted zone both environments' names live in, e.g. tadas.fyi."
  type        = string
}

variable "dns_record_patterns" {
  description = "The record names this role may change, as IAM name patterns. An environment owns its own names and the validation records under them, nothing else in the zone."
  type        = list(string)
}

variable "denied_dns_record_patterns" {
  description = "Record names this role may never change although dns_record_patterns would allow them; production's pattern covers the whole zone, so staging's names are subtracted here."
  type        = list(string)
  default     = []
}

variable "task_boundary_policy_arn" {
  description = "The permissions boundary every role this role creates must carry. A role created without it is refused, so the deploy role cannot mint a task role wider than itself."
  type        = string
}
