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

variable "create_dns_zone" {
  description = "Create the hosted zone for dns_zone_name here. False when the zone already exists in this account, made elsewhere; the environment roots read it by name either way."
  type        = bool
  default     = true
}

variable "operator_principal_arns" {
  description = "Principals besides the tadas-operators user that may assume the investigate roles: a person's own user, or an Identity Center permission set's role. Empty until the team grows."
  type        = list(string)
  default     = []
}

variable "owner_email" {
  description = "Where the budget's notifications and the anomaly monitor's reports go."
  type        = string
}

variable "monthly_budget_usd" {
  description = "The monthly cost budget for the account, in USD. Sized for the demo posture, staging at XS and production at S, which runs about 245 a month; deployment/cloud/README.md prices every size."
  type        = number
  default     = 400
}

variable "anomaly_impact_usd" {
  description = "The absolute impact, in USD, below which a cost anomaly is not reported."
  type        = number
  default     = 20
}
