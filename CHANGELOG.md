# Changelog

The latest release has its entry here. It lists what changed since the
previous tag. A project that clones Tadas at a release checks out its
tag, such as `git clone --branch v0.7.0`.

## 0.18.0 (2026-10-07)

A clone of Tadas at this tag runs each database role on its own
Postgres locally, names the bucket's regional host in an upload's form
and a download's link, and turns Slack on in production; the company
site gains a privacy page. Its pin moves to guideline v0.52.2 by
merging the scaffold seven times: a production run asks a person once,
the long-lived branches are never deleted or rewritten, and every pull
request proves that the release before still passes on its schema. No
route, wire type, or migration changes. One choice of the local stack
is reversed, named below; nothing else is.

- **Each database role runs on its own Postgres locally.** Reversed:
  through 0.17.0 one instance, `postgres` on `TADAS_POSTGRES_PORT`,
  served every role. The compose stack now runs `postgres-core`,
  `postgres-activity`, `postgres-queue`, and `postgres-admin` on 55432
  to 55435, each with its own volume and its own
  `TADAS_POSTGRES_<ROLE>_PORT`, and `.env.example` sets each role's URL
  to its instance, so a statement or a test that leans on two roles
  sharing an instance fails on every local run. `migrate ensure-logins`
  runs on each database a role lives on. Staging and production keep
  one instance for all four (ADR 1001). (#214)
- **Every pull request proves that the release before still passes.**
  CI's `release-before` job, and `make release-before`, migrate the
  local stack to the branch's head and run the integration suite of the
  merge base, and of `release`'s tip, against that schema. `migrate
  stamp` writes the older checkout's version records and applies
  nothing, and refuses a database that is not local. The create run's
  `main` ruleset requires the job (ADR 0084). (#214)
- **A presigned URL names the bucket's regional host.** An upload's
  form and a download's link name `<bucket>.s3.<region>.amazonaws.com`.
  The global host answered a bucket made that day outside `us-east-1`
  with a redirect, which a browser does not follow on a cross-origin
  upload, so every import and attachment upload on a new environment
  failed. (#206)
- **Production turns Slack on.** The production root names the client
  id of production's own Slack app, made from
  `deployment/slack/manifest.production.json`, so the next production
  release starts the API with Slack on. The Slack and Stripe runbooks
  no longer call production parked: it runs on Stripe's live account.
  (#207, #208)
- **The site says what Tadas keeps and shares.** `/privacy.html`,
  linked from the home page's footer, says what Tadas keeps, the five
  services that receive part of it and what each receives, how long
  each kind is kept, how to have it deleted, and whom to ask. Like the
  home page, it loads nothing from another origin and runs no script.
  (#209)
- **An outbound call's breadcrumb keeps its URL's scheme and host
  alone**, no longer its path, so no reply URL's credential reaches the
  error tracker. The portal's error reports cut every URL at its query.
  (#210)
- **The create run names the error tracker** from `error_tracker` in
  `deployment/cloud/environments.json`: its url, its organization, and
  its project, written into the operator's env file. An empty url means
  the deployment has no tracker. (#210)
- **A production run asks a person once**, on the job that holds the
  deploy credential: `apply` on a release, `rollback` on a rollback.
  Every job that declares `production`, in `grant-operator.yml` and
  `state-unlock.yml` too, first refuses an environment with no required
  reviewer. `human-approval.yml` is a reusable approval step for work
  that holds no credential of its own environment (ADR 0082). (#211)
- **`main`, `release`, and `scaffold` are never deleted or rewritten.**
  `scripts/branch_rulesets.sh` sets a ruleset on each that blocks a
  deletion and a force push, with no bypass actor. (#211)
- **`make stop` and `make start` pause the local stack and resume it.**
  `stop` frees the ports and keeps the containers and their data;
  `start` starts what exists, waiting on health, and builds, migrates,
  and seeds nothing. (#212)
- **Fixed.** The local Postgres reads healthy only once it takes a
  connection over TCP, so a service that waits on it is no longer
  refused while an empty data directory initializes. The access line's
  test bounds the line by the relay's measured start, not a fixed
  300 ms. (#215, #216)
- **The pin moves to guideline v0.52.2**, through v0.50.0, v0.51.0,
  v0.51.1, v0.51.2, v0.52.0, and v0.52.1, by merging the scaffold. The
  scaffold's compacted ADRs come in with its words and Tadas's dates and
  product, and its ADR 0083 comes in as ADR 1001, as Tadas's own ADR
  0083 says. (#210, #211, #212, #213, #214, #215, #216)

### What a copy does

- Take the four `TADAS_DATABASE_URL_<ROLE>` lines and the four
  `TADAS_POSTGRES_<ROLE>_PORT` lines from `.env.example` into `.env`,
  in place of a `TADAS_POSTGRES_PORT` it set. Until then every process
  reads every role from the one URL, on the core instance. Then `make
  up` migrates and seeds all four. The core instance's volume is new,
  so the local data starts empty, and the old `postgres` volume stays
  until `docker volume rm` removes it.
- Before its next create run, point `error_tracker` in
  `deployment/cloud/environments.json` at its own tracker, or give it
  an empty url. Set `slack_client_id` in its production root to its own
  app's, or to empty to keep Slack off there.
- Run `scripts/branch_rulesets.sh` once, as a repository administrator.

Every release's notes stay on the repository host: <https://github.com/baristaze/tadas/releases>.
