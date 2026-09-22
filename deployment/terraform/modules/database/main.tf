# One Postgres instance holds every database role until a role moves to its
# own URL (TADAS_DATABASE_URL_<ROLE>). The master password arrives as an
# ephemeral value and is written write-only, so neither the state nor a
# saved plan holds it; it reaches processes only through the secret the
# secrets module writes the same way.

locals {
  tags = { "tadas:environment" = var.environment }
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

  db_name = "tadas"
  # The application's login. On RDS the master user is not a superuser and
  # carries no BYPASSRLS: it is `rds_superuser`, a role that owns the database
  # and is held by every row-level security policy the migrations create, which
  # is what the second tenant fence needs. Nothing here grants it either
  # attribute, and RDS offers no way to.
  username            = "tadas"
  password_wo         = var.master_password
  password_wo_version = var.master_password_version
  port                = 5432

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = var.security_group_ids
  publicly_accessible    = false
  multi_az               = var.multi_az

  backup_retention_period    = var.backup_retention_days
  auto_minor_version_upgrade = true
  # Raising engine_version to a new major upgrades the instance in place.
  allow_major_version_upgrade = true
  # `destroyable` is the nuke's flag, false everywhere but on the apply
  # before the destroy. In staging it lifts the protection. Production's
  # protection comes off only through a released change, never through the
  # flag, and production keeps its final snapshot and its automated backups
  # whatever the flag says: a destroyed production is still restorable. Staging skips both on the way
  # down, so a rebuild finds no snapshot name taken.
  deletion_protection       = var.deletion_protection && !(var.destroyable && var.environment != "production")
  skip_final_snapshot       = var.destroyable && var.environment != "production"
  final_snapshot_identifier = "tadas-${var.environment}-final"
  delete_automated_backups  = var.environment != "production"
  copy_tags_to_snapshot     = true

  tags = local.tags
}
