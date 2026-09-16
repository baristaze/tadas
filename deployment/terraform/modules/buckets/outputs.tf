output "prefix" {
  value = var.prefix
}

output "bucket_names" {
  value = { for name, bucket in aws_s3_bucket.this : name => bucket.bucket }
}

output "policy_arn" {
  description = "Attached to every task role that reads or writes blobs."
  value       = aws_iam_policy.use.arn
}
