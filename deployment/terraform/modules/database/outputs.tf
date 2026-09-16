output "url" {
  description = "The SQLAlchemy URL every role reads until it has its own."
  value       = "postgresql+asyncpg://${aws_db_instance.this.username}:${urlencode(random_password.master.result)}@${aws_db_instance.this.address}:${aws_db_instance.this.port}/${aws_db_instance.this.db_name}"
  sensitive   = true
}

output "address" {
  value = aws_db_instance.this.address
}

output "arn" {
  value = aws_db_instance.this.arn
}
