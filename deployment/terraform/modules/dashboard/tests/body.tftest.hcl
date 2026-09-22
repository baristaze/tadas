# The dashboard body is a shape CloudWatch accepts: every widget's metrics
# is a list of rows, and every row is itself an array (a metric's names, or
# an expression object inside one). A recursive flatten once spread the queue
# rows into loose strings, and PutDashboard refused the whole body. Runs
# offline: `terraform test` in this folder.

mock_provider "aws" {
  mock_data "aws_region" {
    defaults = { region = "us-east-1" }
  }
}

variables {
  environment         = "test"
  cluster_name        = "tadas-test"
  service_names       = ["api", "maintenance"]
  database_identifier = "tadas-test"
  cache_node_ids      = ["tadas-test-001", "tadas-test-002"]
  queue_names         = ["tadas-test-work", "tadas-test-events"]
}

run "every_metric_row_is_an_array" {
  command = plan

  assert {
    condition = alltrue([
      for widget in jsondecode(aws_cloudwatch_dashboard.this.dashboard_body).widgets :
      alltrue([for row in try(widget.properties.metrics, []) : can(row[0])])
    ])
    error_message = "A widget's metrics holds a row that is not an array."
  }

  assert {
    condition = length([
      for widget in jsondecode(aws_cloudwatch_dashboard.this.dashboard_body).widgets :
      widget if length(try(widget.properties.metrics, [])) == 4 && can(regex("SQS", jsonencode(widget.properties.metrics)))
    ]) == 1
    error_message = "The queue widget shows each queue and its dead-letter queue, one row each."
  }
}
