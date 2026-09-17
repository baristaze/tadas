# Terraform

Every cloud resource is declared here; nothing is clicked into place.
Three kinds of root live under this folder:

- `environments/<name>/`: one root per environment (`dev`, `prod`; the
  process reads the name as `TADAS_ENVIRONMENT`, `dev` or `production`).
  Every environment instantiates the same module graph from `main.tf`
  and differs only in `variables.tf`, so a change that works in dev
  reaches production as a scale change. Both take the image digests as
  variables; `.github/workflows/deploy.yml` passes what it built.
- `shared/`: account-level resources every environment uses: the image
  registry (production promotes the digests dev already ran), the state
  bucket, and the deploy role that GitHub's OIDC provider may assume.
- `modules/`: one module per resource family, each with `versions.tf`,
  `variables.tf`, `main.tf`, and `outputs.tf`.

| Module          | Declares                                                        |
|-----------------|-----------------------------------------------------------------|
| `network`       | VPC, public and private subnets, NAT, the security groups        |
| `cluster`       | The container cluster services and workers run on               |
| `database`      | Postgres, its subnet group, the generated master password       |
| `cache`         | Valkey (cache scopes and the topic bus), encrypted in transit   |
| `queue`         | One SQS queue and dead-letter queue per `Queues` member, IAM    |
| `buckets`       | One private versioned bucket per `Buckets` member, IAM          |
| `secrets`       | The injected database URL and the application secrets policy    |
| `load_balancer` | The public edge in front of the API                             |
| `service`       | One process: log group, roles, task definition, service         |

The `service` module is instantiated once per process. A worker passes
`deployment_maximum_percent = 100` so a rollout never runs more workers
than desired, because a worker holds leases.

## State and credentials

Every root declares an empty `backend "s3"` block and receives bucket,
key, and region as `-backend-config` arguments:

```bash
terraform -chdir=deployment/terraform/environments/dev init \
  -backend-config="bucket=$TF_STATE_BUCKET" \
  -backend-config="key=environments/dev/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="use_lockfile=true"
```

The `use_lockfile` option needs Terraform 1.10 or later, which the
roots require. `shared/` creates the state bucket itself: apply it once with local
state, then run `init -migrate-state` against the bucket it made. No
root holds credentials; a developer's AWS profile or the deploy role's
OIDC session provides them.

## Checks

CI runs `terraform fmt -check -recursive` over this folder and
`terraform init -backend=false && terraform validate` in every root.
