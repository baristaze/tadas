# Terraform modules

One module per resource family: network, database, cache, queue,
buckets, service, worker. Every module has `versions.tf`,
`variables.tf`, `main.tf`, and `outputs.tf`. Environments under
`../environments/` compose these modules and differ only in variables.
