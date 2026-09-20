# Terraform

Every cloud resource is declared here; nothing is clicked into place.
Three kinds of root live under this folder:

- `environments/<name>/`: one root per environment (`staging`, `prod`;
  the process reads the name as `TADAS_ENVIRONMENT`, `staging` or
  `production`). A root is thin: its backend, its providers, and one call
  to the `environment` module with its parameter set. The graph lives in
  the module, so a resource is added in one place and the environments
  cannot drift; a new environment is another root, never a copy. Both
  take the image digests as variables: `deploy-staging.yml` passes what
  it built, `deploy-production.yml` the digests it resolves from the
  registry by the commit `release` points at.
- `shared/`: account-level resources every environment uses: the image
  registry (production promotes the digests staging already ran), the state
  bucket, and one deploy role per environment behind GitHub's OIDC
  provider, each trusting a single subject and scoped to what its own
  environment owns (the deploy runbook has the table).
- `modules/`: one module per resource family, each with `versions.tf`,
  `variables.tf`, `main.tf`, and `outputs.tf`.

| Module          | Declares                                                        |
|-----------------|-----------------------------------------------------------------|
| `environment`   | One environment whole: every module below, wired                |
| `deploy_role`   | One environment's deploy role: its OIDC trust and its fences     |
| `network`       | VPC, public and private subnets, NAT, the security groups        |
| `cluster`       | The container cluster services and workers run on               |
| `database`      | Postgres, its subnet group, the generated master password       |
| `cache`         | Valkey (cache scopes and the topic bus), encrypted in transit   |
| `queue`         | One SQS queue and dead-letter queue per `Queues` member, IAM    |
| `buckets`       | One private versioned bucket per `Buckets` member, IAM          |
| `secrets`       | The injected database URL and Sentry DSN, the application secrets policy |
| `load_balancer` | The load balancer at the API's domain name: HTTPS, HTTP redirects |
| `portal`        | The portal's private bucket and the CloudFront distribution at the app's domain name |
| `certificate`   | A DNS-validated ACM certificate for one name                    |
| `domain_records`| The API's and the portal's alias records                        |
| `service`       | One process: log groups, roles, task definition with an ADOT collector sidecar, service |

The `environment` module is the graph itself, and the only module a root
calls. It takes the `aws.us_east_1` provider alias as well as the default
one, because CloudFront reads certificates from that region alone. Its
inputs are the whole difference between two environments: the address
space, the name prefixes, the instance classes, the replica counts, and
the database's multi-az and deletion protection. Reading the two module
calls side by side is how the environments are compared.

The `service` module is instantiated once per process. A worker passes
`deployment_maximum_percent = 100` so a rollout never runs more workers
than desired, because a worker holds leases. The API passes
`pre_rollout_command`, the migration: on every new task definition the
module runs it as a one-off task (`pre_rollout.sh`, from the machine
that applies, with its credentials) and the service depends on it, so a
migration that fails ends the apply with the old tasks still serving.
The worker passes the API's `rollout_gate` as `rollout_after`, so it
rolls after the migration ran. Every service waits for its new tasks to
serve (`wait_for_steady_state`): a rollout ECS rolls back fails the
apply instead of leaving it green over old tasks.

## State and credentials

Every root declares an empty `backend "s3"` block and receives bucket,
key, and region as `-backend-config` arguments:

```bash
terraform -chdir=deployment/terraform/environments/staging init \
  -backend-config="bucket=$TF_STATE_BUCKET" \
  -backend-config="key=environments/staging/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="use_lockfile=true"
```

The `use_lockfile` option needs Terraform 1.10 or later, which the
roots require. `shared/` creates the state bucket itself: apply it once with local
state, then run `init -migrate-state` against the bucket it made. No
root holds credentials; a developer's AWS profile or an environment's
deploy role provides them through its OIDC session. `shared/` is applied
by a person with an administrator profile and never by a deploy run:
every deploy role denies the calls that would change the registry, the
state bucket, or the trust that issues the roles.

## Domains

Each environment has two public names in one Route 53 hosted zone, all three
inputs rather than code:

| Input | staging | production |
|-------|---------|------------|
| `dns_zone_name` | `tadas.fyi` | `tadas.fyi` |
| `api_domain_name` | `api.staging.tadas.fyi` | `api.tadas.fyi` |
| `app_domain_name` | `app.staging.tadas.fyi` | `app.tadas.fyi` |

Each environment has one base domain: production's is the zone itself,
staging's is `staging.` under it, and `api.` and `app.` sit under the base
domain. The two names are inputs, not a computed shape, so any name inside
the zone works; the certificate and the alias record are per name.

The deploy workflows pass them from one repository variable, the zone
(`DNS_ZONE_NAME`): `api.staging.<zone>` and `app.staging.<zone>` for staging,
`api.<zone>` and `app.<zone>` for production. The Terraform variables refuse
a name outside the zone. The zone must already exist in
the account. Terraform does the rest: a DNS-validated certificate per name
(the portal's in us-east-1, where CloudFront reads them), the alias records,
and the API's CORS origin, which is always the app's name. The zone apex, the
company page, is not managed here.

## The portal

The portal is static files: a private S3 bucket that only its CloudFront
distribution can read (origin access control), served at `app_domain_name`.
Client routes such as `/settings` get `index.html` from a CloudFront
Function; hashed assets are cached for a year; `index.html` and `config.json`
revalidate on every load. The API is not behind this distribution: the portal
calls `https://<api_domain_name>` cross-origin, and its realtime WebSocket
connects there directly.

The build carries no environment. Terraform writes `/config.json` per
environment (`apiUrl`, `sentryDsn`, `environment`). `deploy-staging.yml`
builds the portal once, publishes it with `scripts/deploy_portal.sh` after
the apply, and keeps the build by the commit in the state bucket
(`builds/portal/<sha>/`); `deploy-production.yml` publishes those same files
to production. `portal_sentry_dsn`
turns browser error reporting on. The `api_url` and `portal_url` outputs are
where an environment answers.

## Telemetry and error reporting

Each task's collector sidecar scrapes the process's `/metrics` over
localhost every 30 seconds into CloudWatch metrics (namespace `Tadas`,
dimensions `service`, `environment`, and the metric's own labels) and
forwards the traces the process sends to `127.0.0.1:4318` on to X-Ray. The
load balancer answers `/metrics` with a 404, so the endpoint never leaves
the task.

Error reporting stays off until the DSN secret holds a real value. Create a
project in sentry.io or a hosted GlitchTip, then, once per environment:

```bash
aws secretsmanager put-secret-value \
  --secret-id tadas/staging/sentry_dsn --secret-string 'https://<key>@<host>/<project>'
```

Tasks read the secret when they start, so roll the services afterwards
(`aws ecs update-service --force-new-deployment`, or the next deploy).
Terraform never overwrites the value; `off` turns reporting off again.

## Checks

CI runs `terraform fmt -check -recursive` over this folder and
`terraform init -backend=false && terraform validate` in every root.
