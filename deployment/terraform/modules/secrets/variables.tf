variable "environment" {
  description = "Environment name."
  type        = string
}

variable "prefix" {
  description = "Name prefix of every secret this environment owns, e.g. tadas/staging/."
  type        = string
}

variable "database_url" {
  description = "The database URL the database module produced; injected into every task."
  type        = string
  sensitive   = true
}

variable "destroyable" {
  description = "True on the nuke's way down only: the secrets are deleted at once, so a rebuild within the recovery window can create them again under the same names."
  type        = bool
}
