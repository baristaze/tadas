# Tadas, as built

This page describes what exists in this repository. How we build is in
the Software Design and Architecture Guidelines, which this project
adopts unchanged; the technology choices as adopted are recorded in
[ADR 0002](adr/0002-technology-choices.md).

## Object model (`om/`)

The `tadas-om` distribution holds the base classes (`Platform`, the
mixins, `new_id`, `utcnow`), `OpContext` and `AdminContext` with `Role`,
`Permission`, `CredentialKind`, and `AppType` declared beside them, the
exception root, the storage root with its Postgres and memory impls,
and one namespace per swimlane. The context carries ids and facts
(`user_id`, `org_id`, `credential_id`, the role and its permissions),
never a `User` or an `Org`: a manager that needs the entity loads it, so
a role change is seen on the next request, and `opcontext.py` imports
nothing above `base.py`. `Trackable` records who created a row and who
last changed it (`updated_by`); every update sets it from the context.

- `tenancy`: orgs, identities, users, memberships, sessions, api keys,
  socket tickets; sign-in, tenant-scoped session tokens, role-capped api
  keys, the operator allowlist, and the service contexts workers run
  under. The operator plane (every org, delete an org) is a second
  manager, `TenancyOperatorManagerInterface`, which takes `AdminContext`
  and nothing else. A socket ticket is a row; redeeming it is one conditional
  update on its hash, and the cache only remembers a redeemed one so a
  replay is refused without a round trip.
- `work`: the table-backed work queue in the `queue` role; a row's
  routing field is its `lane`, payload shapes are fixed per `WorkKind`
  by `WORK_PAYLOADS`, enqueue validates against it and publishes
  `work_available`, the claim is one `SELECT ... FOR UPDATE SKIP LOCKED`
  statement on the lane and returns the enqueuer's principal. Every
  transition is conditional on the claim (`claimed_by` in the statement),
  so a worker whose lease has passed is refused with `LeaseLost`, a
  `Conflict`; a failed item is a dead letter, named by a
  `work.item.failed` event in the tenant's stream and counted on the
  outcome counter.
- `tasks`: the to-do items (`Task`: title, notes, status), listed by a
  `TaskFilter` (team or mine) and paged by a `TaskCursor`, both passed
  unchanged from the manager to storage; the visibility, cursor, and
  placement rules are pure functions in `tasks.rules`, which the memory
  impl calls and the Postgres impl mirrors in SQL.

- `idempotency`: the durable outcome of a request the caller may retry,
  one record per (tenant, user, key); the gateway begins it before a
  creating request and finishes it with the outcome. A record left
  pending past its lease (a crash between marker and effect) is taken
  over by the next retry, which runs the request again.
- `outbox`: the transactional outbox. A manager that writes a core row
  hands the storage an `OutboxRow` (`kind`, `target_id`, the record's
  snapshot as `payload`, the actor and the request) and the storage base
  inserts both in one commit (`_upsert(..., outbox_row)`, `core` role);
  the manager then calls `OutboxRelayInterface.relay(org_id, row)`,
  which appends the `Event` under the row's id, publishes
  `entity_changed` with `(kind, target_id, seq)`, and marks the row done.
  A relay that fails is logged and counted, never raised; the
  maintenance sweep relays whatever is pending and purges done rows.
- `events`: the append-only stream behind every realtime push, in the
  `activity` role: `Event(Identifiable)` with `seq` (per tenant, gapless,
  assigned by the append, the one number storage assigns), `kind`
  (`<namespace>.<entity>.<action>`, or an audit kind), `target_id`, a
  `payload`, and the actor and request that produced it. The append is
  idempotent on the event id, so relaying an outbox row twice appends
  once. No update, no delete.

Every table belongs to one database role (`core`, `activity`, `queue`,
`admin`); the map in `tadas.om.storage.roles` decides the schema, the
pool, and the migration chain. Migrations are hand-written SQL under
`om/migrations/sql/<role>/` with Alembic wrappers; `core`, `activity`,
and `queue` have chains today, and `admin` has no table yet. Optimistic
concurrency stays opt-in and no table carries a `version` today: nothing
in Tadas has concurrent edits that matter, so last writer wins.

## Infrastructure (`infra/`)

The `tadas-infra` distribution fronts cache, buckets, topics, queues,
and secrets with interfaces, each with a local or memory impl and a
cloud impl (Valkey, S3, SQS, Secrets Manager). Infra imports nothing
from the object model: it has its own frozen model base, its own
exception root (`InfraException`, with the same `http_status` and `code`
shape the platform root has, so the gateway presents both alike), and
the system scope as a value (`SYSTEM_SCOPE`, equal to the model's
`EMPTY_UUID`; a unit test holds the two together). Topics today:
`work_available` (`lane`, `kind`) and `entity_changed` (`kind`,
`target_id`, `seq`); `TopicPayload` is a frozen base declared in infra
with `extra="ignore"`, so a consumer ignores a field it does not know
and producers and consumers roll out in either order. A topic is best
effort. Every capability interface declares `start()` and `close()`; the
roots call them unconditionally and only the Valkey topic listener does
anything in them.

- The queue impls count `sent`, `received`, `deleted`, and, in the
  memory twin where the transition is visible, `dead_lettered` on the
  outcome counter, with a log line naming the message and the queue;
  the twin does not deduplicate on `dedup_id`, exactly like SQS. The
  cache impls count `hit` and `miss` on `get`, and Valkey `unreachable`.
- The AWS impls translate every driver error into `BackendFailed`, an
  `InfraException` leaf (`tadas.infra.exceptions`), through the one
  module that names botocore (`tadas.infra.aws_errors`); not-found
  codes keep their `NotFound` shape.
- Environment names are one set, shared with Terraform: `local` and
  `test` allow the local backends; `dev`, `staging`, and `production`
  refuse them; any other name is refused at boot. The local secrets
  impl receives its `TADAS_SECRET_<NAME>` overrides from the settings
  object, collected once at boot; nothing below settings reads the
  environment. `.env.example` documents every knob.

`InfraConfiguredImpl` picks impls from settings; `InfraLocalImpl` runs
everything in-process for tests.

## Processes

- `services/api` (`tadas-api`): the one API process. Gateway (bearer
  by prefix, `NotAuthenticated` (401) when none or an invalid one is
  presented, request id, error envelope, rate limits keyed on the
  credential id or, on an unauthenticated route, the client address,
  edge idempotency), routers for tenancy, tasks, and the operator plane
  under `/v1/admin/*`, health and metrics outside `/v1`, and the
  realtime channel at `/v1/realtime` opened with a single-use ticket.
  Per socket the process keeps one bounded send buffer
  (`realtime/send_buffer.py`, `TADAS_REALTIME_SEND_BUFFER_SIZE`) and a
  drainer; a full buffer drops the oldest frame and the client replays.
  No service calls another today, so no internal credential is minted;
  `CredentialKind.INTERNAL` is what the seeding and the worker's service
  contexts carry.
  `tadas-api serve | migrate | bootstrap | add-member | openapi`
  (`bootstrap` and `add-member` are what `make seed` runs; both produce
  the context the seeding then runs under).
- `workers/maintenance` (`tadas-maintenance`): the claim loop for kind
  `NOOP` on one lane (`TADAS_WORKER_LANE`, or `serve --lane`), lease
  renewal and self-fencing, a liveness heartbeat in the cache, and the
  maintenance sweep (requeue stale leases under one service context per
  live tenant, then purge the tenant's soft-deleted tasks, removed
  members, and revoked api keys past their retention (the one hard
  delete, 30 days by default), then relay the pending outbox rows and
  purge the done ones). `tadas-maintenance serve | health`: the
  image's `HEALTHCHECK` runs `health`, which reads the serving worker's
  liveness key through the same cache and exits non-zero when it is
  missing. It serves its own `/metrics` on `TADAS_METRICS_PORT` (9464).
- Every Python process boots error reporting (the Sentry SDK, on only when
  `TADAS_SENTRY_DSN` is set: unhandled exceptions and ERROR log lines,
  tagged with `service` and `request_id`), tracing (OpenTelemetry, on only
  when `TADAS_OTEL_ENDPOINT` is set), and Prometheus metrics, all from
  `tadas.infra.observability`.
- `apps/portal` (`@tadas/portal`): React, Vite, TanStack Query,
  Zustand; sign-in, the tasks screen at `/` (My and Team's tasks, open in
  manual order, done newest first with Show more, inline edit, drag to
  reorder), settings at `/settings` (members, api keys, sign-out), and one
  realtime channel that invalidates queries by the entity name inside a
  push's `kind`. The client keeps the last contiguous `seq`; a push ahead
  of it is a replay of `/v1/events` after the cursor, never a skip.
  Errors go to the Sentry-compatible backend named by `VITE_SENTRY_DSN`,
  through every route's `errorElement` and React's root error hooks. The
  API is reached through `src/api/`: the committed `openapi.json` at the
  app root, generated types behind the facade `types.ts`, one transport
  client. There is no Python client yet; the only Python caller is the
  demo recorder ([ADR 0004](adr/0004-demo-recorder-calls-the-api-directly.md)).

## Deployment (`deployment/`)

- `local/`: the compose stack (Postgres, Valkey, ElasticMQ, MinIO, and,
  under the `devx` profile, developer dashboards plus Prometheus, Grafana,
  Jaeger, and a seeded GlitchTip) and a second file that adds the
  application containers, the portal among them.
- `docker/`: one two-stage image per process, non-root, with a
  healthcheck (`/healthz` for the API, `tadas-maintenance health` for
  the worker, `/` for the portal's nginx).
- `terraform/`: every cloud resource. `modules/` holds one module per
  resource family (`network`, `cluster`, `database`, `cache`, `queue`,
  `buckets`, `secrets`, `load_balancer`, `certificate`, `domain_records`,
  `portal`, `service`); `environments/dev` and `environments/prod`
  instantiate the same graph and differ only in variables, including
  the image digests; `shared/` holds the registry, the state bucket, and
  the deploy role. The load balancer's idle timeout is read from
  `deployment/realtime-timeouts.json`, the file the api and the portal
  pin their ping interval against. The worker's service instance
  caps a rollout at 100% of desired because a worker holds leases. Every
  task runs an ADOT collector sidecar that scrapes the process's
  `/metrics` into CloudWatch (namespace `Tadas`) and forwards its traces to
  X-Ray; the load balancer answers `/metrics` with a 404. Errors report to
  the DSN in the `<prefix>sentry_dsn` secret, which starts as `off`. The
  module README explains state and credentials.
- `.github/workflows/ci.yml`: the fast gate, the integration job (which
  runs `make migrate-check` right after `make migrate`), an image build
  per Dockerfile, and `terraform fmt -check` plus `validate` per root.
  `deploy.yml` builds and pushes both images by digest and the portal
  once, plans dev (the plan goes to the job summary, its text to the
  `dev-plan` artifact, the saved plan to the state bucket), pauses for
  `human_approval`, applies the approved plan, runs the migration as a
  one-off task (`scripts/cloud_migrate.sh`), publishes the portal
  (`scripts/deploy_portal.sh`), and then, behind the `production`
  environment's approval, applies production with the same digests and
  publishes the same portal files. Its first job checks the repository
  variables (`AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET`, `DNS_ZONE_NAME`);
  while they are empty every cloud job is skipped, the summary says so,
  and the run stays green.
- `.github/workflows/human_approval.yml`: the pause, a reusable workflow
  with one job bound to the `human_approval` GitHub environment, whose
  required reviewer is the owner. A job requires it with `needs:` after
  `uses: ./.github/workflows/human_approval.yml`; Approve lets the run
  go on, Reject cancels what needs it. `deploy.yml` requires it in one
  place, before the first `terraform apply`. `human_approval_smoke.yml`
  is its self-test, run by hand. [The deploy runbook](runbooks/deploy.md)
  says what to check at the pause.
- Public names are inputs: the API at `api_domain_name` (the load balancer,
  e.g. `api.tadas.fyi`, `dev-api.tadas.fyi` for dev) and the portal at
  `app_domain_name` (a private S3 bucket behind CloudFront, e.g.
  `app.tadas.fyi`), with certificates and records in one Route 53 zone. The
  portal reads `/config.json`, written per environment by Terraform, before
  it renders, and calls the API cross-origin; locally it falls back to the
  `VITE_` build variables.

## Checks

Rules a program can check are checked in `om/tests/unit/`:
`test_import_direction.py` scans every module under `tadas.om` and
`tadas.infra` statically and fails on an import of a service or a
worker, on an infra module importing the object model, or on an
object-model module outside `tadas.om.root` importing an infra impl
rather than an interface. `test_storage_exceptions.py` lists every
storage method that does not take `org_id` first and every manager
operation that does not take a context, each with its stated reason. `make migrate-check` compares
every role's ORM metadata with the migrated schema; it needs the compose
database, so CI's integration job runs it and the fast gate does not
([ADR 0003](adr/0003-migrate-check-in-the-integration-job.md)).

## Decisions

See [docs/adr/](adr/).
