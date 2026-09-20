output "topic_arn" {
  description = "Where every alarm goes; another address subscribes to it by hand."
  value       = aws_sns_topic.alarms.arn
}

output "alarm_names" {
  description = "Every alarm the environment declares, for a reader that lists their states."
  value = concat(
    [
      aws_cloudwatch_metric_alarm.http_5xx_ratio.alarm_name,
      aws_cloudwatch_metric_alarm.unhealthy_targets.alarm_name,
      aws_cloudwatch_metric_alarm.http_p95_latency.alarm_name,
      aws_cloudwatch_metric_alarm.database_cpu.alarm_name,
      aws_cloudwatch_metric_alarm.database_free_storage.alarm_name,
    ],
    [for alarm in aws_cloudwatch_metric_alarm.tasks_below_desired : alarm.alarm_name],
  )
}
