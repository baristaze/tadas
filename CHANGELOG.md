# Changelog

Each release has an entry here, the newest first. An entry lists what
changed since the previous tag. A project that clones Tadas at a release
checks out its tag, such as `git clone --branch v0.7.0`.

## 0.11.0 (2026-09-30)

The two operational skills read a deployed environment: each signal
they report has its cloud call, on the schema the app's series carry.
The pin moves to guideline v0.42.0 by merging the scaffold. No route,
wire type, screen, or migration changes.

- **`ops-investigate` reads the requests of a deployed environment.**
  Step 4 searches the schema the app's series carry, with the
  exporter's `OTelLib`. The schema it wrote before matched no series,
  so the request query read zero. (#187)
- **Each skill gives the cloud call of every signal it reports.**
  `ops-watch` step 5 prints a batch's four numbers in one call: the
  requests, the 5xx, the p95, and the worker's failures.
  `ops-investigate` reads the request count, the counts by status and
  route, the p95, the outcomes, and the database's connections. (#187)
- **The cloud p95 is the load balancer's**: one number for every route
  together, in milliseconds, or `none` when no request crossed it. The
  cloud has no p95 by route. (#187)
- **A watch batch that read nothing says so.** In the cloud, a batch
  whose `requests` is 0 writes "metrics not read", never a zero: the
  load balancer's health checks are requests. (#187)
- **`ops-investigate` asks the error tracker for a window it takes.**
  Step 6 sends Sentry's own host the search term `lastSeen:-<since>`
  and keeps the issues by their `lastSeen` field. It sends no
  `statsPeriod`, which answered the default hour with a 400. (#187)
- **Tests hold the skills' schemas.** `infra/tests/test_ops_skills.py`
  holds every `SEARCH` schema the two skills write to the ones the
  dashboard module writes. (#187)
- **The guideline pin moves to v0.42.0.** `main` merges the `scaffold`
  branch at v0.42.0. `make arch-check` passes at v0.42.0, and nothing
  the release asks is a deviation. (#187)

## 0.10.0 (2026-09-30)

Tadas is its scaffold plus its product. Every file the scaffold also
holds takes the scaffold's text, and what stays different is the
product, the environments, and the history. The pin moves to guideline
v0.41.0 by merging the scaffold. The API gains one route, for the
identity provider's deliveries. No wire type, screen, or migration
changes.

- **The identity provider's signed deliveries come in.**
  `POST /webhooks/identity` takes them, beside the payment processor's
  and Slack's routes. It checks the signature and queues the delivery,
  and the maintenance worker records an org's event as the audit entry
  `identity.event.received`. With `TADAS_WORKOS_WEBHOOK_SECRET` unset
  or `off`, the route answers 503 to every delivery. Each environment's
  Terraform creates the secret and gives it to the API, and it stays
  `off` until a person writes it. (#181, #182)
- **The guideline pin moves to v0.41.0.** `main` holds the scaffold
  base in its history and merges the `scaffold` branch at v0.41.0.
  `make arch-check` passes at v0.41.0, and ADR 0083 records what the
  release asks: nothing of it is a deviation. (#179, #184)
- **The Python packages are the scaffold's, plus the product.** `om`,
  `infra`, `integrations`, `services`, `workers`, `clients/python`, and
  `ops` take the scaffold's text. The worker's consumer of deliveries
  is the scaffold's registry of providers. (#182)
- **The apps and the TypeScript client are the scaffold's, plus the
  product.** Settings reads storage through the scaffold's storage
  model. `ApiError` takes the plan's bound as its last argument. Stored
  preferences drop a field they do not know, and a stored scope that is
  not one reads as the default. (#183)
- **The local stack takes the scaffold's defaults.** Every host port
  the compose stack publishes is a knob in `.env.example`. MinIO's
  local password and the bucket prefix `tadas-local` are the
  scaffold's: an older `.env` takes `TADAS_S3_SECRET_KEY` and
  `TADAS_S3_BUCKET_PREFIX` from `.env.example`. The local TOTP key is
  the scaffold's too: a local operator enrolled under the old key
  keeps that key in `.env`, or makes the local database again with
  `make reset`. (#181, #184)
- **The deployment** takes the scaffold's text. Each root's sign-in
  client id is a variable that defaults to the real id, and the
  dashboard's `SEARCH` quotes its namespace. (#181)
- **The ops and audit skills** take the scaffold's text, and they name
  the identity provider's deliveries. (#181, #184)
- **The docs and the ADRs take the scaffold's text,** with Tadas's
  product, environments, and history: `docs/`, the README, `llms.txt`,
  `specs/architecture.md`, and the issue templates. ADRs 0010, 0027,
  and 0061 keep their names and take the scaffold's text of the same
  decisions. (#180)

## 0.9.0 (2026-09-30)

Tadas's base is the guideline's scaffold, and the pin moves to v0.40.0
by merging it. The portal, the command line, and the API work as they
did at 0.8.0: no route, wire type, screen, or migration changes.

- **Tadas is based on the guideline's scaffold.** The branch `scaffold`
  holds swe_guidelines' `scaffold/acme_root/` as Tadas took it, renamed
  to `tadas`: v0.39.0, then v0.40.0. `main` merges that branch, so a
  later release comes in by a merge, and
  `/swe-guidelines:arch-upgrade-scaffold` makes the move. (#177)
- **The guideline pin moves to v0.40.0.** `make arch-check` passes at
  v0.40.0, and ADR 0082 records what the release asks: ADRs 0011, 0027,
  and 0040 are no longer deviations, and 0041 and 0067 keep one part
  each. (#177)
- **The ops skills** take the scaffold's added bounds and steps. (#177)

## 0.8.0 (2026-09-29)

Tadas moves to the shape of the guideline at v0.39.0. The portal, the
command line, and the API work as they did at 0.7.0: no route, wire
type, screen, or migration changes.

- **The guideline pin moves to v0.39.0,** by way of v0.38.0.
  `make arch-check` passes at v0.39.0, and ADRs 0080 and 0081 record
  where Tadas stands on each rule the two releases change. (#173, #174)
- **A tenant operation's context is `TenantContext`.** `OpContext` is
  renamed, and its module `tadas.om.opcontext` is `tadas.om.context`.
  Code built on Tadas imports the new names. (#174)
- **The TypeScript client is a package of its own.** `@tadas/client`,
  in `clients/typescript/`, holds the one transport, the generated
  types, and the OpenAPI document, which was `apps/portal/openapi.json`.
  The portal imports it alone, and a new browser app imports it too.
  (#171)
- **The ops skills live in `.agents/skills/`,** where any agent that
  reads the Agent Skills standard finds them, and `.claude/skills`
  links there. Every loop a skill runs has a count: a watch's batches,
  a query's polls, the request ids a root cause follows, and the hops
  of Next. (#170, #173)
- **The docs tell the story for two readers.** `docs/architecture.md`
  is gone: the guideline holds the shape, the tree is the system as
  built, and `docs/adr/` records each decision. The README and
  `llms.txt` take the scaffold's shape and keep the product story.
  (#172)
- **The deviations table lists live deviations only.** Each row in
  `specs/architecture.md` names its rule, the section the rule cites,
  and that section's tag at v0.39.0. There are 14. (#175)
- **CI** runs `astral-sh/setup-uv` 10.2.0. (#169)

## 0.7.0 (2026-09-27)

The first tagged release. Tadas is a multi-tenant to-do application for
teams of people and the agents that work alongside them, built in the
shape of the Software Design and Architecture Guidelines, pinned at
v0.37.0. This entry says what the system does at this tag. Every entry
after it lists the changes since the tag before.

- **Tasks for teams.** A person has a personal org and can create team
  orgs, switch between them, hand one on, or delete it. A task has a
  due date, an assignee, and attachments. Quick add is one text box,
  and the task list offers bulk actions with Undo.
- **Realtime.** Every change reaches every open portal and every
  `tadas listen` over one realtime channel. A client that falls behind
  the event stream resyncs.
- **The portal, the command line, and a Python client.** The portal is
  a browser app. `tadas` works one command at a time or listens. The
  Python client covers the public API under `/v1`, described by the
  committed OpenAPI document.
- **Sign-in and billing.** People sign in through WorkOS AuthKit, and
  sessions last 30 days, or 14 idle. API keys and operator credentials
  have budgets and end on their own. Billing runs through Stripe, and
  seats follow the org's members.
- **Slack.** The Slack app is installed per org, over HTTP.
- **Background work.** An outbox relays every write, a work queue and
  its worker run the jobs, and a sweep sends reminders, runs
  long-running orchestrations such as a task import, and purges what
  retention ends.
- **Operations.** It deploys to AWS with Terraform. `main` deploys to
  staging, and the `release` branch, moved by a workflow, deploys to
  production. Alarms cover the queue, the outbox, and failed rows, and
  a local stack runs everything in containers with `make up`.
