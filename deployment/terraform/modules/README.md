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
  registry by the commit `release` points at. Each pins its provider to
  its environment's account.
- `bootstrap/<name>/`: one root per environment's AWS account (`staging`,
  `prod`). Each environment has an account of its own, and
  `deployment/cloud/environments.json` names it. A bootstrap root calls
  the `account` module and adds the roles its deploy workflow assumes,
  each trusting a single subject (the deploy runbook has the table).
  Staging's also replicates every image and portal build into
  production's account; production's grants those two writes and nothing
  else. `scripts/cloud_create.sh` applies it, under the account's
  administrator profile.
- `modules/`: one module per resource family, each with `versions.tf`,
  `variables.tf`, `main.tf`, and `outputs.tf`.

| Module          | Declares                                                        |
|-----------------|-----------------------------------------------------------------|
| `environment`   | One environment whole: every module below, wired                |
| `account`       | One environment's account before its first deploy: the registry, the state bucket, the OIDC provider, the task boundary, the investigate role, the budget and anomaly monitor, one hosted zone per public name |
| `deploy_role`   | One environment's deploy role: its OIDC trust and its fences     |
| `investigate_role` | One environment's read-only role: ReadOnlyAccess plus the signal reads, fenced off secrets, data, the database, the other environment, and IAM |
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
| `service`       | One process: log groups, roles, task definition with an ADOT collector sidecar, service, and its autoscaling target and policy behind the switch |
| `alarms`        | The default alarm set to one SNS topic: the edge, the database, each service's task count |
| `dashboard`     | The CloudWatch dashboard, from a JSON template carrying the local Grafana dashboard's panels by title |

The `environment` module is the graph itself, and the only module a root
calls. It takes the `aws.us_east_1` provider alias as well as the default
one, because CloudFront reads certificates from that region alone. Its
inputs are the whole difference between two environments: the address
space, the name prefixes, the instance classes, the replica counts, the
database's pool size, and the database's multi-az and deletion
protection. What each set of numbers costs is in
[../../cloud/README.md](../../cloud/README.md). Reading the two module
calls side by side is how the environments are compared.

Three inputs of the `environment` module are operations rather than
scale. `alarm_email` is where the environment's seven alarms deliver.
`autoscaling_enabled` is the one flip: each service's lever under it
(`api_autoscaling`, `maintenance_autoscaling`: a ceiling, a CPU target,
and `enabled = true` by default) takes effect only when it is true, and
both roots declare it false (docs/runbooks/scale.md). `destroyable` is
the nuke's flag, false everywhere but on `scripts/cloud_nuke.sh`'s way
down: it lets the buckets empty on destroy and lifts the database's
protection and final snapshot.

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
  -backend-config="bucket=tadas-state-<account>" \
  -backend-config="key=environments/staging/terraform.tfstate" \
  -backend-config="region=us-west-2" \
  -backend-config="use_lockfile=true"
```

The `use_lockfile` option needs Terraform 1.10 or later, which the
roots require. Each account has its own state bucket,
`tadas-state-<account>`: the bootstrap root's state sits at
`bootstrap/terraform.tfstate`, the environment root's under
`environments/staging/` or `environments/prod/`. A bootstrap root creates
its bucket itself: it applies once with local state, then runs `init
-migrate-state` against the bucket it made. No root holds credentials; a
person's Identity Center profile or an environment's deploy role
provides them through its OIDC session. A bootstrap root is applied by
its account's administrator and never by a deploy run: every deploy role
denies the calls that would change the registry, its replication, the
state bucket, or the trust that issues the roles.

## Domains

Each environment has two public names, and each name is the apex of a
Route 53 hosted zone of its own in the environment's account:

| Input | staging | production |
|-------|---------|------------|
| `api_domain_name` | `api.staging.tadas.fyi` | `api.tadas.fyi` |
| `app_domain_name` | `app.staging.tadas.fyi` | `app.tadas.fyi` |

The names are written once, in `deployment/cloud/environments.json`. The
bootstrap root makes the two zones. The domain itself is registered at
Cloudflare, which keeps its zone, so `scripts/cloud_create.sh` delegates
each name there with NS records naming its zone's servers. The create
script also sets the names as the `API_DOMAIN_NAME` and `APP_DOMAIN_NAME`
variables of the environment's GitHub environments, and the deploy
workflows pass them in. The environment root finds each zone by its name.
Terraform does the rest: a DNS-validated certificate per name (the
portal's in us-east-1, where CloudFront reads them), the alias records,
and the API's CORS origin, which is always the app's name. The domain's
apex, the company page, is not managed here.

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
the apply, and keeps the build by the commit in staging's artifacts bucket
(`tadas-artifacts-<account>`, under `builds/portal/<sha>/`). The state
bucket holds state and nothing else. The artifacts bucket replicates the
build into production's, and
`deploy-production.yml` publishes those same files to production from
there. `portal_sentry_dsn`, the root's variable, turns browser error
reporting on; the deploy workflows pass it from the `PORTAL_SENTRY_DSN`
variable of the environment's GitHub environment, and an unset one
leaves reporting off. The `api_url` and `portal_url` outputs are
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

CI runs `terraform fmt -check -recursive` over this folder,
`terraform init -backend=false && terraform validate` in every root, and
`terraform test` in `modules/portal` (the security headers) and in
`modules/service` (the autoscaling switch), both offline under a mock
provider. `infra/tests/test_dashboard_parity.py` holds the dashboard
template's panel titles equal to the local Grafana dashboard's.
