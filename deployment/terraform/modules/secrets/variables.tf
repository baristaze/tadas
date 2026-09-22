variable "environment" {
  description = "Environment name."
  type        = string
}

variable "prefix" {
  description = "Name prefix of every secret this environment owns, e.g. tadas/staging/."
  type        = string
}

variable "database_password" {
  description = "The master password, generated for the run and never stored; the URL is written write-only."
  type        = string
  sensitive   = true
  ephemeral   = true
}

variable "database_password_version" {
  description = "The database module's password version; a bump writes the URL again."
  type        = number
}

variable "database_username" {
  type = string
}

variable "database_address" {
  type = string
}

variable "database_port" {
  type = number
}

variable "database_name" {
  type = string
}

variable "destroyable" {
  description = "True on the nuke's way down only: the secrets are deleted at once, so a rebuild within the recovery window can create them again under the same names."
  type        = bool
}
