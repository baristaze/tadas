# The API's public surface: an application load balancer at the API's domain
# name. HTTPS serves the API and its realtime WebSocket; HTTP redirects.

locals {
  tags = { "tadas:environment" = var.environment }
}

resource "aws_lb" "this" {
  name                       = "tadas-${var.environment}"
  load_balancer_type         = "application"
  subnets                    = var.subnet_ids
  security_groups            = var.security_group_ids
  drop_invalid_header_fields = true
  tags                       = local.tags
}

resource "aws_lb_target_group" "api" {
  name                 = "tadas-${var.environment}-api"
  port                 = var.target_port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 30
  tags                 = local.tags

  health_check {
    path                = var.health_check_path
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  tags              = local.tags

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"
  tags              = local.tags

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# /metrics is for the collector sidecar, which scrapes it over localhost inside
# the task; the internet gets a 404 before the request reaches a target.
resource "aws_lb_listener_rule" "hide_metrics" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 1
  tags         = local.tags

  condition {
    path_pattern {
      values = ["/metrics", "/metrics/*"]
    }
  }

  action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "Not Found"
      status_code  = "404"
    }
  }
}
