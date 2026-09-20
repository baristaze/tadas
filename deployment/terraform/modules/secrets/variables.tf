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
