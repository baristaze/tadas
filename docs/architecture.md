# Tadas, as built

This page describes what exists in this repository. How we build is in
the Software Design and Architecture Guidelines, which this project
adopts unchanged; the technology choices as adopted are recorded in
[ADR 0002](adr/0002-technology-choices.md).

## Object model (`om/`)

The `tadas-om` distribution holds the base classes (`Platform`, the
mixins, `new_id`, `utcnow`), `OpContext` and `AdminContext`, the
exception root, the storage root with its Postgres and memory impls,
and one namespace per swimlane:

- `tenancy`: orgs, identities, users, memberships, sessions, api keys;
  sign-in, tenant-scoped session tokens, role-capped api keys, the
  operator allowlist, and the service contexts workers run under.
- `work`: the table-backed work queue in the `queue` role; enqueue
  publishes `work_available`, the claim is one `SELECT ... FOR UPDATE
  SKIP LOCKED` statement and returns the enqueuer's principal.
- `tasks`: the to-do items (`Task`: title, notes, status), a feed with
  the `(org_id, id)` index.

Every table belongs to one database role (`core`, `activity`, `queue`,
`admin`); the map in `tadas.om.storage.roles` decides the schema, the
pool, and the migration chain. Migrations are hand-written SQL under
`om/migrations/sql/<role>/` with Alembic wrappers; `core` and `queue`
have chains today.

## Infrastructure (`infra/`)

The `tadas-infra` distribution fronts cache, buckets, topics, queues,
and secrets with interfaces, each with a local or memory impl and a
cloud impl (Redis, S3, SQS, Secrets Manager). Topics today:
`work_available` and `entity_changed`. Every capability interface
declares `start()` and `close()`; the roots call them unconditionally
and only the Redis topic listener does anything in them.

- The queue impls count `sent`, `received`, `deleted`, and, in the
  memory twin where the transition is visible, `dead_lettered` on the
  outcome counter, with a log line naming the message and the queue;
  the twin does not deduplicate on `dedup_id`, exactly like SQS. The
  cache impls count `hit` and `miss` on `get`, and Redis `unreachable`.
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
  by prefix, request id, error envelope, rate limits, edge
  idempotency), routers for tenancy, tasks, and the operator plane
  under `/v1/admin/*`, health and metrics outside `/v1`, and the
  realtime channel at `/v1/realtime` opened with a single-use ticket.
  `tadas-api serve | migrate | bootstrap | openapi`.
- `workers/maintenance` (`tadas-maintenance`): the claim loop for kind
  `NOOP`, lease renewal and self-fencing, a liveness heartbeat in the
  cache, and the maintenance sweep (requeue stale leases, one service
  context per live tenant). `tadas-maintenance serve | health`: the
  image's `HEALTHCHECK` runs `health`, which reads the serving worker's
  liveness key through the same cache and exits non-zero when it is
  missing.
- `apps/portal` (`@tadas/portal`): React, Vite, TanStack Query,
  Zustand; sign-in, the home screen (members, api keys), and one
  realtime channel that invalidates queries by entity name.
- `clients/api-client` (`@tadas/api-client`): the committed
  `openapi.json`, generated types behind a facade, one transport
  client.

## Deployment (`deployment/`)

- `local/`: the compose stack (Postgres, Redis, ElasticMQ, MinIO, and
  developer dashboards under the `devx` profile) and a second file that
  adds the application containers, the portal among them.
- `docker/`: one two-stage image per process, non-root, with a
  healthcheck (`/healthz` for the API, `tadas-maintenance health` for
  the worker, `/` for the portal's nginx).
- `terraform/`: every cloud resource. `modules/` holds one module per
  resource family (`network`, `cluster`, `database`, `cache`, `queue`,
  `buckets`, `secrets`, `load_balancer`, `service`); `environments/dev`
  and `environments/prod` instantiate the same graph and differ only in
  variables, including the image digests; `shared/` holds the registry,
  the state bucket, and the deploy role. The worker's service instance
  caps a rollout at 100% of desired because a worker holds leases. The
  module README explains state and credentials.
- `.github/workflows/ci.yml`: the fast gate, the integration job (which
  runs `make migrate-check` right after `make migrate`), an image build
  per Dockerfile, and `terraform fmt -check` plus `validate` per root.
  `deploy.yml` builds and pushes both images by digest, applies dev,
  runs the migration as a one-off task (`scripts/cloud_migrate.sh`),
  and then, behind the `production` environment's approval, applies
  production with the same digests.

## Checks

Rules a program can check are checked in `om/tests/unit/`:
`test_import_direction.py` scans every module under `tadas.om` and
`tadas.infra` statically and fails on an import of a service or a
worker, or on an object-model module outside `tadas.om.root` importing
an infra impl rather than an interface. `make migrate-check` compares
every role's ORM metadata with the migrated schema; it needs the compose
database, so CI's integration job runs it and the fast gate does not.

## Decisions

See [docs/adr/](adr/).
