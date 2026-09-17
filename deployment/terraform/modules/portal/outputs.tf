output "bucket_name" {
  description = "Where the deploy uploads the built portal."
  value       = aws_s3_bucket.this.id
}

output "distribution_id" {
  description = "Invalidated after each upload of index.html."
  value       = aws_cloudfront_distribution.this.id
}

output "url" {
  description = "Where the portal, and the API under /v1, answer."
  value       = "https://${length(var.aliases) > 0 ? var.aliases[0] : aws_cloudfront_distribution.this.domain_name}"
}
