# Tadas, as built

This page describes what exists in this repository. How we build is in
the Software Design and Architecture Guidelines, which this project
adopts unchanged; the technology choices as adopted are recorded in
[ADR 0002](adr/0002-technology-choices.md).

## Object model (`om/`)

The `tadas-om` distribution holds the base classes (`Platform`, the
mixins, `new_id`, `utcnow`), the context model in `opcontext.py` with
`Role`, `Permission`, `CredentialKind`, and `AppType` declared beside it,
the exception root, the storage root with its Postgres and memory impls,
and one namespace per swimlane. `Trackable` records who created a row
and who last changed it (`updated_by`); every update sets it from the
context.

The context model is two orthogonal ideas. The stages are four frozen
types ordered by evidence: `RequestContext` (a request exists: its id,
the calling app, the trace id), `IdentityContext` (a person is verified
by their own sign-in; no tenant, on purpose), `OpContext` (a membership
is established: the user, the org, the role and its permissions, the
credential), and `OperatorContext` (an identity on the operator allowlist;
no org, on purpose). A subclass is a refinement, so every stage is
accepted where `RequestContext` is asked for; `OperatorContext` is an
`IdentityContext`, `OpContext` is not, because what a tenant operation
knows about the person is the user inside the tenant. A stage above the
request stage is produced only by a transition, an operation of the
tenancy manager or one that asks it, and nowhere else
(`authenticate_login`, `authenticate`, `admit_operator`,
`redeem_ticket`, `service_context`, the worker's claim, and the
seeding), and a function that
takes a stage relies on its invariant instead of re-checking it. The
context carries ids and facts, never a `User` or an `Org`: a manager that
needs the entity loads it, so a role change is seen on the next request,
and `opcontext.py` imports nothing above `base.py`.

The scopes are five `Protocol` views over what a stage carries, each a
set of read-only properties: `RequestScope`, `TenantScope`, `ActorScope`
(there is no actor without a tenant), `CredentialScope`, and
`ProvenanceScope` (actor, request, and app: the one named composition,
because provenance is a domain concept). A function that reads only a
few fields declares the scope it reads (`outbox_row` and `audit_event`
take `ProvenanceScope`, the realtime `subscribe` takes `ActorScope`, the
rate limit's subject takes `CredentialScope`) and its callers keep
passing the stage they hold. A manager operation takes `OpContext`, which
is its scope, and says nothing narrower; a function that forwards the
context on keeps the stage the callee needs.

- `tenancy`: orgs, identities, users, memberships, sessions, api keys,
  socket tickets; sign-in, tenant-scoped session tokens, role-capped api
  keys, the operator allowlist, and the service contexts workers run
  under. Permissions are a function of role, one table in
  `tenancy.types.role`; the ladder beside it ranks the person roles
  (viewer, member, admin, owner) and a unit test holds it to the table, so
  a role at most another holds a subset of its permissions. The service
  role is no rung: `role_at_most` answers False on either side of it, and
  every operation that issues a credential or grants a membership refuses
  it by name before the ladder is asked. The operator plane (every org, delete an org) is a second
  manager, `TenancyOperatorManagerInterface`, which takes `OperatorContext`
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
  creating request and finishes it with the outcome. The record carries
  the id the create uses, minted by the gateway before the marker. A
  record left pending past its lease (a crash between marker and
  outcome) is taken over by the next retry, which runs the request
  again on that id; a create that finds its own id already written
  returns the row as stored, so the rerun cannot create twice. The one
  create that issues a secret, the api key, is the exception: the secret
  is stored as a digest and shown once, and the first one reached no one
  when the marker stored no outcome, so its rerun re-mints the secret on
  the row the id names, in the same storage method that inserts it
  (`issue_api_key`, one conditional write on the issuer's row, no second
  outbox row), and returns a fresh `IssuedApiKey` with the same id; the
  old secret stops authenticating. A failure (a `5xx`) is not an outcome:
  the marker is released and the retry runs again; a refusal (a `4xx`) is
  stored and replayed.
- `outbox`: the transactional outbox. A manager that writes a core row
  hands the storage an `OutboxRow` (`kind`, `target_id`, the record's
  snapshot as `payload`, the actor and the request) and the storage base
  inserts both in one commit (`_insert(..., outbox_row)` for a create, which
  reports an existing id and changes nothing then; `_upsert(..., outbox_row)`
  for an update; `core` role);
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
with `extra="ignore"`, so a consumer ignores a field it does not know;
a payload gains only optional, defaulted fields, so an old producer's
message and a queued row written before a deploy still parse, and the
two sides roll out in either order. A topic is best effort. Every capability interface declares `start()` and `close()`; the
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
  The gateway mints the request stage once per request
  (`request_context`: the request id the middleware stamped, `X-App`
  and `X-App-Version`, the current trace id) and asks the tenancy
  manager for every stronger stage: `Ctx` is `authenticate` over the
  bearer (a session token or an api key), `Identity` is
  `authenticate_login` over it (the sign-in credential, on the tenant
  choice and the operator gate), `OperatorCtx` is `admit_operator` over the
  identity, and the socket builds the request stage from its scope and
  redeems its ticket. The login route takes the request stage alone.
  Per socket the process keeps one bounded send buffer
  (`realtime/send_buffer.py`, `TADAS_REALTIME_SEND_BUFFER_SIZE`) and a
  drainer; a full buffer drops the oldest frame and the client replays.
  No service calls another today, so no internal credential is minted;
  `CredentialKind.INTERNAL` is what the seeding and the worker's service
  contexts carry. The sweep's service contexts are minted for the tenant,
  not for a member: each carries the tenant, the service role, and the
  system user (`EMPTY_UUID`) as its actor, at one read per page of
  tenants, so a tenant whose members have all left is still swept; the
  claim of a work item still rebuilds the enqueuer's principal under the
  service role, so attribution survives the asynchronous hop.
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
  purge the done ones after eight days, which outlives the seven-day
  database backup retention, so a role restored to an earlier point
  than its siblings is reconciled by relaying the outbox again). `tadas-maintenance serve | health`: the
  image's `HEALTHCHECK` runs `health`, which reads the serving worker's
  liveness key through the same cache and exits non-zero when it is
  missing. It serves its own `/metrics` on `TADAS_METRICS_PORT` (9464).
- Every Python process builds its roots whole at boot, once: storage,
  infra, then every manager, in dependency order; a request constructs
  nothing. The cost is the imports (about 450 ms, once per process);
  a root itself builds in microseconds. `make benchmark-boot` measures it;
  [ADR 0007](adr/0007-roots-built-whole-at-boot.md) says why a lazy
  root is refused.
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
  client. Every push and every event record carry `actor_id`, so a client
  can say who changed what, and the hello frame and every pong carry
  the stream position (`seq`), so a client replays from there after a
  reconnect even when no push reached it before the drop, and a push
  that was dropped with nothing behind it is found on the next
  keepalive rather than on the next event.
- `clients/python` (`tadas-client`, `tadas.client`): the one Python client,
  generated from the same committed `openapi.json` (`schema.py`, by
  `make openapi`) behind the facade `types.py`; one transport client with
  the error envelope, idempotency keys, and the OS trust store; the socket
  frames mirrored by hand (`envelopes.py`); the placement rule
  (`stream.py`); and the channel (`realtime.py`): ticket, one
  subscription, pings, gaps replayed from `/v1/events`, reconnect with
  backoff. The demo recorders use it; the interval before it existed is
  [ADR 0004](adr/0004-demo-recorder-calls-the-api-directly.md).
- `apps/cli` (`tadas-cli`, `tadas`): Typer over the Python client. Command
  mode (`add`, `ls`, `edit`, `done`, `reopen`, `rm`, `mv`) does one call
  and exits with 0, 1 (refused), 2 (usage), 3 (not signed in), or 4
  (unreachable); `listen` prints every task change as one line (who did
  what to which task) as it arrives on the channel, `--mine` for the
  caller's own. `login` keeps a session token under `TADAS_HOME`;
  `TADAS_TOKEN` (a session token or an api key) and `TADAS_API_URL` win
  over it. The rules of what is shown live in `model.py`, pure and unit
  tested; the commands run in tests against the whole API in-process.

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
storage method that does not take `org_id` first, asserts every manager
operation takes a context stage first (the outbox relay is the stated
exception), and names the transitions that take `RequestContext` or
`IdentityContext`, so a new principal-less operation must be listed.
`test_stage_construction.py` scans every source tree (`om`, `infra`,
`services`, `workers`, `apps`, `clients`) for a site that constructs
`IdentityContext`, `OpContext`, or `OperatorContext` or calls
`build_context`, and fails when one appears that is not the tenancy
manager's transitions or the helper they use, so only a transition
produces a stage above the request stage. `test_role_rules.py` holds the
role ladder to the permission table and keeps the service role off it.
`test_interfaces.py` fails on a `*Interface` under `tadas.om` or
`tadas.infra` that is not an `ABC` with every public method abstract.
Each process's `tests/test_settings.py` (and `infra/tests/`) reads
`.env.example` and fails on a settings field it does not document, and
reads every Terraform environment and fails on a field the cloud neither
sets nor lists, with a reason, as one it leaves at the local default.
`make migrate-check` compares
every role's ORM metadata with the migrated schema; it needs the compose
database, so CI's integration job runs it and the fast gate does not
([ADR 0003](adr/0003-migrate-check-in-the-integration-job.md)).

## Decisions

See [docs/adr/](adr/).

### Considered

Shapes a sibling system (xtadas, the one-shot scaffold benchmark) has and
this one does not, judged and not taken, or not yet:

- **A TypeScript client as its own workspace package** (`clients/api-client`
  beside `clients/python`). "Clients Live in One Place" read literally; the
  portal today keeps the committed `openapi.json`, the generated types, the
  facade, and the transport client under `apps/portal/src/api/`, which is one
  place while the portal is the only TypeScript caller. The move is real and
  mechanical (a package with its own `tsconfig`, the portal importing it,
  `make openapi` regenerating into it) and it pays off the day a second
  TypeScript app arrives; it is not taken before then.
- **A server-side scope on the realtime subscription** (`subscribe` with
  `scope: team | mine`, the push carrying the record's assignee and creator
  so the server filters by audience). Not taken: every push carries the
  tenant's stream position and both clients hold a contiguous cursor, so a
  push the server withholds is a gap to them, and the next push that arrives
  replays `/v1/events` after the cursor, which is unscoped and hands back what
  was withheld. A scoped subscription would either cost a replay per filtered
  push or need a scoped replay and a per-subscription frame counter to keep
  the dropped-frame guarantee, a second protocol. The "mine" rule stays where
  it is, in the client (`model.py`, the portal's scoped lists), until the
  channel carries enough traffic that filtering at the server pays for the
  protocol it needs.
