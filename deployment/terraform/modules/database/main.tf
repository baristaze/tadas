# One Postgres instance holds every database role until a role moves to its
# own URL (TADAS_DATABASE_URL_<ROLE>). The master password is generated here
# and reaches processes only through the secret the secrets module writes.

locals {
  tags = { "tadas:environment" = var.environment }
}

resource "random_password" "master" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "this" {
  name       = "tadas-${var.environment}"
  subnet_ids = var.subnet_ids
  tags       = local.tags
}

resource "aws_db_instance" "this" {
  identifier     = "tadas-${var.environment}"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.allocated_storage * 5
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "tadas"
  username = "tadas"
  password = random_password.master.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = var.security_group_ids
  publicly_accessible    = false
  multi_az               = var.multi_az

  backup_retention_period    = var.backup_retention_days
  auto_minor_version_upgrade = true
  deletion_protection        = var.deletion_protection
  skip_final_snapshot        = !var.deletion_protection
  final_snapshot_identifier  = "tadas-${var.environment}-final"
  copy_tags_to_snapshot      = true

  tags = local.tags
}
