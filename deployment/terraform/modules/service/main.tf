locals {
  tags = {
    "tadas:service"     = var.name
    "tadas:environment" = var.environment
  }
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/tadas/${var.environment}/${var.name}"
  retention_in_days = 30
  tags              = local.tags
}
