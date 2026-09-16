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
`work_available` and `entity_changed`. `InfraConfiguredImpl` picks
impls from settings and refuses local backends in staging and
production; `InfraLocalImpl` runs everything in-process for tests.

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
  context per live tenant).
- `apps/portal` (`@tadas/portal`): React, Vite, TanStack Query,
  Zustand; sign-in, the home screen (members, api keys), and one
  realtime channel that invalidates queries by entity name.
- `packages/api-client` (`@tadas/api-client`): the committed
  `openapi.json`, generated types behind a facade, one transport
  client.

## Decisions

See [docs/adr/](adr/).
