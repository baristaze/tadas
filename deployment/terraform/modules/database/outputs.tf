output "username" {
  value = aws_db_instance.this.username
}

output "port" {
  value = aws_db_instance.this.port
}

output "db_name" {
  value = aws_db_instance.this.db_name
}

output "address" {
  value = aws_db_instance.this.address
}

output "arn" {
  value = aws_db_instance.this.arn
}

output "identifier" {
  description = "The instance identifier, the dimension its CloudWatch metrics carry."
  value       = aws_db_instance.this.identifier
}
