# Local stack

Two compose files and one profile make up everything that runs locally.
Every command below runs from the repository root.

| File or profile | Adds |
|-----------------|------|
| `docker-compose.yml` | Postgres, Valkey, ElasticMQ (its queues in `elasticmq/elasticmq.conf`), MinIO |
| `docker-compose.full.yml` | the `api`, `maintenance`, and `portal` containers, built from the working tree |
| profile `devx` (in `docker-compose.yml`) | pgweb, Valkey Admin, ElasticMQ UI, Prometheus, the OpenTelemetry collector for host processes, Grafana, Jaeger, GlitchTip |
| `docker-compose.linux.yml` | Linux only, added by the Makefile: the collector on the host's network (see Metrics below) |

The compose project is `tadas`, so containers are named `tadas-<service>-1`
and the volumes `tadas_postgres` and `tadas_minio`.

## URLs and ports

Everything listens on 127.0.0.1 only. `make urls` prints the browser URLs.
The dashboard ports below are the defaults of the `TADAS_<DASHBOARD>_PORT`
knobs in `.env.example`; a clash is fixed by setting the knob in `.env`.
The data services' ports are fixed, since the `TADAS_*_URL` knobs name them.

| Service | From the host | Inside the compose network | Sign-in |
|---------|---------------|----------------------------|---------|
| portal | http://localhost:55173 | `portal:8080` | at `/login/dev`, by address: `owner@example.test` (owner) or `bob@example.test` (member) of Acme, or `admin@admin.test` (owner of Fabrikam, admin of Acme) (after `make seed`), each with a personal org beside; at `/login`, anyone through WorkOS's staging environment once `TADAS_WORKOS_API_KEY` is set in the shell or `.env` |
| api | http://127.0.0.1:8000 (`/docs`, `/metrics`, `/healthz`) | `api:8000` | |
| postgres | `127.0.0.1:55432` | `postgres:5432` | database `tadas`; `tadas_runtime`, `tadas_system`, and `tadas_migration`, each with its name as its password; the master `tadas` / `tadas`; the superuser `postgres` / `postgres` |
| valkey | `127.0.0.1:56379` | `valkey:6379` | none: user `default`, no password |
| elasticmq (SQS) | http://127.0.0.1:59324 | `elasticmq:9324` | any key; `tadas-webhooks` and its `-dead` queue are declared in `elasticmq/elasticmq.conf` |
| minio (S3) | http://127.0.0.1:59000 | `minio:9000` | `tadas` / `tadastadas`; `make infra-up` and `make up` create the buckets (`make buckets`), and the app containers sign presigned URLs for the host port |
| MinIO console | http://localhost:59001 | | `tadas` / `tadastadas` |
| pgweb (devx) | http://localhost:58081 | | none |
| Valkey Admin (devx) | http://localhost:58080 | | none; see below |
| ElasticMQ UI (devx) | http://localhost:53000 | | none |
| Prometheus (devx) | http://localhost:59090 | `prometheus:9090` | none |
| Grafana (devx) | http://localhost:53001 | | none (anonymous admin) |
| Jaeger UI (devx) | http://localhost:56686 | | none |
| Jaeger OTLP (devx) | http://127.0.0.1:54318 | `jaeger:4318` | none |
| GlitchTip (devx) | http://localhost:58000 | `glitchtip:8000` | `admin@example.test` / `tadas-local` |
| maintenance metrics | http://127.0.0.1:9464/metrics (host process only) | `maintenance:9464` | |

`maintenance` publishes no port; its healthcheck asks its own `/healthz`,
which answers from the loop's last beat in memory, and Prometheus scrapes
its `/metrics` inside the network. The `otel-collector` service publishes
no port either and listens on nothing.

Postgres has five logins, and only `postgres` is a superuser.

- `tadas_runtime` is what every request's connection uses. It owns nothing
  and holds DML only, so no statement that reaches it can drop a policy,
  turn `FORCE` off, or alter a table.
- `tadas_system` is its twin for the system scope, on a pool of its own. The
  policies admit the system scope to it alone, so the runtime login naming
  the system scope reads nothing.
- `tadas_migration` owns every role schema and table, and runs the
  migrations and the integration suite's truncation between cases.
- `tadas` is the local master, as the master user is in the cloud. The init
  script in `postgres/initdb/` creates it `LOGIN NOSUPERUSER NOBYPASSRLS
  CREATEROLE` and makes it the owner of the database. It opens one command,
  `migrate ensure-logins`, which `make migrate` runs first: it makes the
  three logins above with the passwords their URLs carry, hands the
  migration login the schemas, and grants the other two their DML. It is
  safe to run again.
- `postgres` is the superuser, for the things a fenced login may not do:
  creating GlitchTip's database, and pgweb, which is there to show every
  row.

None of the first four is a superuser or carries `BYPASSRLS`. Either
attribute would walk past every row-level security policy, and those
policies are the second tenant fence, so a login that carries one turns the
fence into a drawing. The init script runs once, on an empty data directory,
so a stack that was up before `tadas` could create roles needs `make reset`,
or `ALTER ROLE tadas CREATEROLE` as `postgres`.

The local Valkey has no authentication: every client is the built-in
`default` user, with no password and full access. Valkey Admin still asks
for a connection the first time. It connects from inside the compose
network, so enter host `valkey` and port `6379` (not `localhost` or
`56379`), leave username and password empty, and leave TLS off. Its
`VALKEY_HOST` and `VALKEY_PORT` settings only start its background metrics.

## Whole stack

| Goal | Command |
|------|---------|
| Everything up, migrated and seeded; keeps data | `make up` |
| Stop everything, keep data | `make down` |
| Wipe all data and start over | `make reset` |
| Only the backing services (for `scripts/dev.sh`) | `make infra-up` |
| Backing services plus dashboards | `make devx-up` |
| Backing services plus app containers, no dashboards | `make stack-up` |

## One service at a time

Set this once per shell. It names both files and the profile, so every
service is addressable:

```bash
alias dc='docker compose --env-file .env.example --env-file .env -f deployment/local/docker-compose.yml -f deployment/local/docker-compose.full.yml --profile devx'
```

On Linux, add `-f deployment/local/docker-compose.linux.yml` after the first
file, as the Makefile does, or `dc up` puts the collector back on the compose
network, where it cannot reach the host processes.

| Goal | Command |
|------|---------|
| What is running, with health | `dc ps` |
| Follow one service's logs | `dc logs -f api` |
| Rebuild and restart only the API after a code change | `dc up -d --build --wait api` |
| Rebuild the portal (also after changing `VITE_API_URL`) | `dc up -d --build --wait portal` |
| Restart a service without rebuilding | `dc restart maintenance` |
| Stop the app containers, keep the backing services (to switch to `scripts/dev.sh`) | `dc stop api maintenance portal` |
| Start only the dashboards | `dc up -d pgweb valkey-admin elasticmq-ui prometheus otel-collector grafana jaeger glitchtip` |
| Stop only the dashboards | `dc stop pgweb valkey-admin elasticmq-ui prometheus otel-collector grafana jaeger glitchtip` |
| Apply new migrations | `make migrate` |
| Seed again, or other people | `make seed SEED_EMAIL=me@example.test SEED_MEMBER_EMAIL=you@example.test SEED_ADMIN_EMAIL=both@example.test SEED_SLUG=mine SEED_SECOND_SLUG=theirs`, or set the `SEED_*` knobs in `.env` |
| Record the README's demo GIF (empties the task list first) | `make demo-gif` |
| Add one more member to the seeded org | `uv run --package tadas-api tadas-api add-member --slug acme --email carol@example.test --name Carol`, then sign in as her at `/login/dev` |

## Data

| Goal | Command |
|------|---------|
| A `psql` shell | `dc exec postgres psql -U tadas` |
| A `valkey-cli` shell | `dc exec valkey valkey-cli` |
| Clear the cache and rate limits (sessions live in Postgres) | `dc exec valkey valkey-cli flushall` |
| List the SQS queues | `curl -s 'http://127.0.0.1:59324/?Action=ListQueues'` |
| Reset only the database, then migrate and seed | `dc rm -sfv postgres && docker volume rm tadas_postgres && dc up -d --wait postgres && make migrate seed` |
| Reset only the object store | `dc rm -sfv minio && docker volume rm tadas_minio && dc up -d --wait minio && make buckets` |

ElasticMQ keeps nothing: `dc restart elasticmq` empties every queue. It
starts with the queues `elasticmq/elasticmq.conf` declares: `tadas-webhooks`
and `tadas-slack`, each with a `-dead` queue after five receives, as the
cloud's queue module declares them.

## Slack

The stack holds no Slack connection and sets no `TADAS_SLACK_*`, so the
`maintenance` container posts through the in-process twin. Local and
staging share one Slack app, and Slack spreads its deliveries across every
open connection, so a bridge left running on a laptop takes deliveries
meant for staging. To try the real thing, run the bridge by hand, briefly,
with the tokens exported for that run only:

```bash
TADAS_SLACK_APP_TOKEN=xapp-... uv run tadas-maintenance slack
```

It sends each delivery to `tadas-slack`, where the worker takes it. A host
worker posts to Slack only with `TADAS_SLACK_BOT_TOKEN` set for its run.
Valkey has no named volume but snapshots on shutdown, so `dc restart valkey`
keeps its keys; `flushall` above empties it, and `make reset` removes it.

## Metrics, traces, and errors

Everything below needs the `devx` profile (`make up` or `make devx-up`).

- **Metrics.** The api serves `/metrics` on its own port, the worker on
  `TADAS_METRICS_PORT` (9464). As containers (`api:8000`,
  `maintenance:9464`), Prometheus scrapes them itself. As host processes,
  which `scripts/dev.sh` binds to 127.0.0.1, an OpenTelemetry collector
  scrapes them and remote-writes into Prometheus
  (`otel-collector/collector.yml`, and `--web.enable-remote-write-receiver`
  on Prometheus). That is the shape of the cloud's sidecar, which scrapes
  its process over localhost, and it keeps the processes off every other
  interface. The series carry the same labels either way: `job` (`api`,
  `maintenance`), `instance`, and `runs_in` (`container` or `host`).
  Whichever of the two is not running reads `up == 0`, which is expected;
  http://localhost:59090/targets lists only the container targets, and
  `up{runs_in="host"}` is the collector's view of the host processes.
- **The collector's one switch.** Two settings place the collector: the
  host it scrapes and the URL it writes to. By default it runs on the
  compose network, scrapes `host.docker.internal:8000` and `:9464`, and
  writes to `http://prometheus:9090/api/v1/write`. On Linux,
  `host.docker.internal` is the Docker bridge gateway, which a loopback
  listener never answers, so the Makefile adds `docker-compose.linux.yml`
  when `uname -s` says Linux. That file puts the collector on the host's
  network, where it scrapes `127.0.0.1:8000` and `:9464` and writes to
  `http://127.0.0.1:${TADAS_PROMETHEUS_PORT}/api/v1/write`, host to
  container, the way traces reach Jaeger. It listens on nothing, so the
  host gains no port.
- **The api's port is a knob.** The api job has one host target, and the
  `8000` in it is `TADAS_COLLECTOR_SCRAPE_PORT`. `make collector-scrape
  SCRAPE_PORT=54321` points the collector somewhere else and recreates it,
  since a collector reads a changed config no other way; `make
  collector-scrape` with no argument puts it back on the `.env` port. The
  telemetry round trip runs both: it takes a free port for its own api, aims
  the collector at it, and restores the default when it is done, so the
  round trip no longer needs 8000 to itself. Grafana
  opens on the provisioned Tadas overview dashboard (requests, statuses,
  p95 latency, cache, queue, and worker outcomes). Dashboards changed in the
  UI are lost with the container; export them into
  `grafana/dashboards/` to keep them.
- **Traces.** The app containers export to Jaeger (`TADAS_OTEL_ENDPOINT` in
  `docker-compose.full.yml`). Host processes export only when
  `TADAS_OTEL_ENDPOINT=http://127.0.0.1:54318` is set in `.env`. Grafana's
  Jaeger data source shows the same traces.
- **Errors.** GlitchTip is Sentry-compatible. `glitchtip-db` creates its
  database on the stack's Postgres and `glitchtip-seed` creates the admin
  and one project, `tadas`, whose DSN key is fixed. So the DSNs are known
  ahead of time: `http://0123456789abcdef0123456789abcdef@glitchtip:8000/1`
  in the app containers, and the same key at `localhost:58000` or
  `127.0.0.1:58000` for the portal and host processes (`TADAS_SENTRY_DSN`
  and `VITE_SENTRY_DSN` in `.env.example`). Unhandled exceptions and ERROR
  log lines become issues, tagged with `service`, `release`,
  `request_id`, and `environment`. An empty or `off` DSN turns reporting
  off. The one project is the local stand-in for the product's one
  project in the cloud: there too every environment reports into one
  project and the `environment` tag separates them, which locally is
  `local`, so `tadas-ops signals check --env local` reads exactly the
  way it reads staging.

## When something is off

| Symptom | Likely cause and fix |
|---------|----------------------|
| `postgres` exits right after start | A volume from another Postgres major version. `make reset`, or reset only the database as above. |
| `api` exits at start with `Failed connecting to valkey` | Valkey was not reachable yet as the API booted. `dc up -d --wait api`. |
| `port is already allocated` | Another process holds that host port: `lsof -nP -iTCP:<port> -sTCP:LISTEN`. For a dashboard, set its `TADAS_<DASHBOARD>_PORT` in `.env`. |
| The portal loads but every request fails | The API is down, or the portal was built for another `VITE_API_URL`: `dc ps api`, then rebuild the portal. |
| The API refuses to start, naming a setting | `.env` predates a rename; compare it with `.env.example`. |
| `scripts/dev.sh` fails on port 8000 | The `api` container is running: `dc stop api maintenance portal`. |
