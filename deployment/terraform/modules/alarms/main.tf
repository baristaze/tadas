# The default alarm set of one environment, and the one topic they all go
# to: the edge (5xx ratio, unhealthy targets, p95 latency), one per read
# that has a latency of its own to keep (GET /v1/billing), the database
# (CPU, free storage), and the runtime (a service running fewer tasks than
# it wants, one per service). The thresholds are inputs with defaults here, at the
# leaf, because a threshold is a number and not shape; an environment that
# wants another number passes it through the environment module, which
# exposes none of them yet.
#
# The first responder is an agent holding the investigate role: it reads the
# alarm against the platform's size before it escalates, so the topic's
# subscribers are the people who are told, not the people who act first.

locals {
  tags = { "tadas:environment" = var.environment }

  # The alarm's name carries the environment so an email says which one.
  prefix = "tadas-${var.environment}"

  # Both ALB metrics take the load balancer's ARN suffix as the dimension;
  # the target group metrics take both.
  load_balancer = { LoadBalancer = var.load_balancer_arn_suffix }
  target_group = {
    LoadBalancer = var.load_balancer_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }
}

resource "aws_sns_topic" "alarms" {
  name = "${local.prefix}-alarms"
  tags = local.tags
}

# One address by declaration. Another person subscribes with
# `aws sns subscribe`; the runbook says how, and Terraform leaves it alone.
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# The edge.

resource "aws_cloudwatch_metric_alarm" "http_5xx_ratio" {
  alarm_name          = "${local.prefix}-http-5xx-ratio"
  alarm_description   = "More than ${var.http_5xx_ratio_percent} percent of requests answered 5xx, by the load balancer or by a target, for ${var.evaluation_periods} periods of ${var.period_seconds}s."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.evaluation_periods
  threshold           = var.http_5xx_ratio_percent
  # No requests is not an outage; it is a quiet environment.
  treat_missing_data = "notBreaching"
  alarm_actions      = [aws_sns_topic.alarms.arn]
  ok_actions         = [aws_sns_topic.alarms.arn]
  tags               = local.tags

  # The load balancer publishes a 5xx count only for a minute that has one,
  # and metric math yields nothing where any input is missing, so each count
  # is filled with zero: 5xx from targets alone, or from the load balancer
  # alone, still makes a ratio.
  metric_query {
    id          = "ratio"
    expression  = "100 * (FILL(target_5xx, 0) + FILL(elb_5xx, 0)) / requests"
    label       = "5xx percent"
    return_data = true
  }

  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "RequestCount"
      period      = var.period_seconds
      stat        = "Sum"
      dimensions  = local.load_balancer
    }
  }

  metric_query {
    id = "target_5xx"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_Target_5XX_Count"
      period      = var.period_seconds
      stat        = "Sum"
      dimensions  = local.load_balancer
    }
  }

  metric_query {
    id = "elb_5xx"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_ELB_5XX_Count"
      period      = var.period_seconds
      stat        = "Sum"
      dimensions  = local.load_balancer
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_targets" {
  alarm_name          = "${local.prefix}-unhealthy-targets"
  alarm_description   = "At least one API target failed the load balancer's health check for ${var.evaluation_periods} periods of ${var.period_seconds}s."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  dimensions          = local.target_group
  statistic           = "Maximum"
  period              = var.period_seconds
  evaluation_periods  = var.evaluation_periods
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "http_p95_latency" {
  alarm_name          = "${local.prefix}-http-p95-latency"
  alarm_description   = "The load balancer's p95 target response time exceeded ${var.http_p95_latency_seconds}s for ${var.evaluation_periods} periods of ${var.period_seconds}s."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = local.load_balancer
  extended_statistic  = "p95"
  period              = var.period_seconds
  evaluation_periods  = var.evaluation_periods
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.http_p95_latency_seconds
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = local.tags
}

# One read's own latency. The load balancer's p95 is every route together,
# so a slow read that is a small share of the traffic never moves it. The
# API writes each request's route and time as fields of its access line, and
# a metric filter on its log group turns one route's lines into a metric of
# raw values, from which CloudWatch computes a true p95.

locals {
  # A route template as an alarm name can carry it: /v1/billing is v1-billing.
  read_latency_slugs = {
    for route, seconds in var.read_latency_p95_seconds :
    route => trim(replace(route, "/[^a-zA-Z0-9]+/", "-"), "-")
  }
}

resource "aws_cloudwatch_log_metric_filter" "read_latency" {
  for_each = var.read_latency_p95_seconds

  name           = "${local.prefix}-read-latency-${local.read_latency_slugs[each.key]}"
  log_group_name = var.api_log_group_name
  pattern        = "{ $.http.method = \"GET\" && $.http.route = \"${each.key}\" }"

  metric_transformation {
    name       = "tadas_read_latency_ms"
    namespace  = "Tadas"
    value      = "$.http.duration_ms"
    unit       = "Milliseconds"
    dimensions = { route = "$.http.route" }
  }
}

resource "aws_cloudwatch_metric_alarm" "read_latency" {
  for_each = var.read_latency_p95_seconds

  alarm_name          = "${local.prefix}-read-latency-${local.read_latency_slugs[each.key]}"
  alarm_description   = "GET ${each.key} answered slower than ${each.value}s at p95 for ${var.evaluation_periods} periods of ${var.period_seconds}s, as the API timed it."
  namespace           = "Tadas"
  metric_name         = "tadas_read_latency_ms"
  dimensions          = { route = each.key }
  extended_statistic  = "p95"
  period              = var.period_seconds
  evaluation_periods  = var.evaluation_periods
  comparison_operator = "GreaterThanThreshold"
  threshold           = each.value * 1000
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = local.tags

  depends_on = [aws_cloudwatch_log_metric_filter.read_latency]
}

# The database.

resource "aws_cloudwatch_metric_alarm" "database_cpu" {
  alarm_name          = "${local.prefix}-database-cpu"
  alarm_description   = "The database's CPU stayed above ${var.database_cpu_percent} percent for ${var.evaluation_periods} periods of ${var.period_seconds}s."
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = var.database_identifier }
  statistic           = "Average"
  period              = var.period_seconds
  evaluation_periods  = var.evaluation_periods
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.database_cpu_percent
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = local.tags
}

# Storage autoscales up to a ceiling; this fires when the free space under
# the current allocation runs low, which is early enough to read why.
resource "aws_cloudwatch_metric_alarm" "database_free_storage" {
  alarm_name          = "${local.prefix}-database-free-storage"
  alarm_description   = "The database has less than ${var.database_free_storage_bytes} bytes of free storage."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = var.database_identifier }
  statistic           = "Minimum"
  period              = var.period_seconds
  evaluation_periods  = var.evaluation_periods
  comparison_operator = "LessThanThreshold"
  threshold           = var.database_free_storage_bytes
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = local.tags
}

# The runtime: one alarm per service, on the gap between what it wants and
# what runs. Container Insights publishes both counts per service; the gap
# is a metric math expression so a scale-out (desired rises, running follows)
# reads the same as a deploy. Its window is longer than the others: the worker
# rolls one task at a time with no second one beside it, so a routine deploy
# leaves it at none for its drain plus a start, a few minutes that are not an
# outage.
resource "aws_cloudwatch_metric_alarm" "tasks_below_desired" {
  for_each = toset(var.service_names)

  alarm_name          = "${local.prefix}-${each.key}-tasks-below-desired"
  alarm_description   = "The ${each.key} service ran fewer tasks than it wants for ${var.tasks_below_desired_periods} periods of ${var.period_seconds}s."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.tasks_below_desired_periods
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = local.tags

  metric_query {
    id          = "gap"
    expression  = "desired - running"
    label       = "tasks missing"
    return_data = true
  }

  metric_query {
    id = "desired"
    metric {
      namespace   = "ECS/ContainerInsights"
      metric_name = "DesiredTaskCount"
      period      = var.period_seconds
      stat        = "Maximum"
      dimensions  = { ClusterName = var.cluster_name, ServiceName = each.key }
    }
  }

  metric_query {
    id = "running"
    metric {
      namespace   = "ECS/ContainerInsights"
      metric_name = "RunningTaskCount"
      period      = var.period_seconds
      stat        = "Minimum"
      dimensions  = { ClusterName = var.cluster_name, ServiceName = each.key }
    }
  }
}
