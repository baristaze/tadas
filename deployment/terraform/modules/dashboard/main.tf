# One environment's operator dashboard, the cloud twin of the Grafana
# dashboard the local profile provisions (deployment/local/grafana/dashboards/
# tadas-overview.json). The first five widgets carry that dashboard's panel
# titles, one for one, and a unit test holds the two lists equal; the last
# row is what only the cloud has: the database, the cache, the queue, and
# the tasks.
#
# The body is dashboard.json.tftpl, a JSON document with interpolations and
# nothing else (no template loops), so the test can read it as JSON. The
# list-valued widgets receive their metric arrays as JSON fragments built
# here.
#
# The application metrics come from the `Tadas` namespace the collector
# sidecar exports to, with every Prometheus label as a dimension and no
# rollups (the service module's `NoDimensionRollup`): a rollup would drop the
# environment dimension and merge the two environments' series, since both
# live in one account. So CloudWatch has one series per label combination and
# no group-by. "By route" is therefore every combination, labelled by its
# values; "by status" is one sum per status code, listed below.

data "aws_region" "current" {}

locals {
  running_tasks = [
    for name in var.service_names :
    ["ECS/ContainerInsights", "RunningTaskCount", "ClusterName", var.cluster_name, "ServiceName", name, { label = name }]
  ]

  # SUM over every route and method for one status code; the collector's
  # counters arrive as one-minute deltas, so the sum over a 60s period
  # divided by 60 is a rate per second.
  responses_by_status = [
    for status in var.http_statuses :
    [{
      expression = "SUM(SEARCH('{Tadas,environment,method,route,service,status} MetricName=\"tadas_http_requests_total\" environment=\"${var.environment}\" status=\"${status}\"', 'Sum', 60)) / 60"
      label      = tostring(status)
      id         = "s${status}"
    }]
  ]

  cache_cpu = [
    for id in var.cache_node_ids :
    ["AWS/ElastiCache", "EngineCPUUtilization", "CacheClusterId", id, { label = id }]
  ]

  queue_depths = flatten([
    for name in var.queue_names : [
      ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", name, { label = "${name} visible" }],
      ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", "${name}-dead", { label = "${name} dead" }],
    ]
  ])
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = "tadas-${var.environment}"

  dashboard_body = templatefile("${path.module}/dashboard.json.tftpl", {
    environment         = var.environment
    region              = data.aws_region.current.region
    database_identifier = var.database_identifier
    running_tasks       = jsonencode(local.running_tasks)
    responses_by_status = jsonencode(local.responses_by_status)
    cache_cpu           = jsonencode(local.cache_cpu)
    queue_depths        = jsonencode(local.queue_depths)
  })
}
