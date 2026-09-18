# Local stack

Two compose files and one profile make up everything that runs locally.
Every command below runs from the repository root.

| File or profile | Adds |
|-----------------|------|
| `docker-compose.yml` | Postgres, Valkey, ElasticMQ, MinIO |
| `docker-compose.full.yml` | the `api`, `maintenance`, and `portal` containers, built from the working tree |
| profile `devx` (in `docker-compose.yml`) | pgweb, Valkey Admin, ElasticMQ UI, Prometheus, Grafana, Jaeger, GlitchTip |

The compose project is `tadas`, so containers are named `tadas-<service>-1`
and the volumes `tadas_postgres` and `tadas_minio`.

## URLs and ports

Everything listens on 127.0.0.1 only. `make urls` prints the browser URLs.
The dashboard ports below are the defaults of the `TADAS_<DASHBOARD>_PORT`
knobs in `.env.example`; a clash is fixed by setting the knob in `.env`.
The data services' ports are fixed, since the `TADAS_*_URL` knobs name them.

| Service | From the host | Inside the compose network | Sign-in |
|---------|---------------|----------------------------|---------|
| portal | http://localhost:55173 | `portal:8080` | `owner@example.test` (owner) or `bob@example.test` (member), both `tadas-local` (after `make seed`) |
| api | http://127.0.0.1:8000 (`/docs`, `/metrics`, `/healthz`) | `api:8000` | |
| postgres | `127.0.0.1:55432` | `postgres:5432` | `tadas` / `tadas`, database `tadas` |
| valkey | `127.0.0.1:56379` | `valkey:6379` | none: user `default`, no password |
| elasticmq (SQS) | http://127.0.0.1:59324 | `elasticmq:9324` | any key |
| minio (S3) | http://127.0.0.1:59000 | `minio:9000` | `tadas` / `tadastadas` |
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

`maintenance` publishes no port; its healthcheck reads its liveness key in
Valkey, and Prometheus scrapes its `/metrics` inside the network.

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
| Wipe all data and stop | `make infra-down` |
| Only the backing services (for `scripts/dev.sh`) | `make infra-up` |
| Backing services plus dashboards | `make devx-up` |
| Backing services plus app containers, no dashboards | `make stack-up` |

## One service at a time

Set this once per shell. It names both files and the profile, so every
service is addressable:

```bash
alias dc='docker compose -f deployment/local/docker-compose.yml -f deployment/local/docker-compose.full.yml --profile devx'
```

| Goal | Command |
|------|---------|
| What is running, with health | `dc ps` |
| Follow one service's logs | `dc logs -f api` |
| Rebuild and restart only the API after a code change | `dc up -d --build --wait api` |
| Rebuild the portal (also after changing `VITE_API_URL`) | `dc up -d --build --wait portal` |
| Restart a service without rebuilding | `dc restart maintenance` |
| Stop the app containers, keep the backing services (to switch to `scripts/dev.sh`) | `dc stop api maintenance portal` |
| Start only the dashboards | `dc up -d pgweb valkey-admin elasticmq-ui prometheus grafana jaeger glitchtip` |
| Stop only the dashboards | `dc stop pgweb valkey-admin elasticmq-ui prometheus grafana jaeger glitchtip` |
| Apply new migrations | `make migrate` |
| Seed again, or other people | `make seed SEED_EMAIL=me@example.test SEED_MEMBER_EMAIL=you@example.test SEED_PASSWORD=secret SEED_SLUG=mine`, or set the `SEED_*` knobs in `.env` |
| Record the README's demo GIF (empties the task list first) | `make demo-gif` |
| Add one more member to the seeded org | `uv run --package tadas-api tadas-api add-member --slug acme --email carol@example.test --password tadas-local --name Carol` |

## Data

| Goal | Command |
|------|---------|
| A `psql` shell | `dc exec postgres psql -U tadas` |
| A `valkey-cli` shell | `dc exec valkey valkey-cli` |
| Clear the cache and rate limits (sessions live in Postgres) | `dc exec valkey valkey-cli flushall` |
| List the SQS queues | `curl -s 'http://127.0.0.1:59324/?Action=ListQueues'` |
| Reset only the database, then migrate and seed | `dc rm -sfv postgres && docker volume rm tadas_postgres && dc up -d --wait postgres && make migrate seed` |
| Reset only the object store | `dc rm -sfv minio && docker volume rm tadas_minio && dc up -d --wait minio` |

ElasticMQ keeps nothing: `dc restart elasticmq` empties every queue.
Valkey has no named volume but snapshots on shutdown, so `dc restart valkey`
keeps its keys; `flushall` above empties it, and `make reset` removes it.

## Metrics, traces, and errors

Everything below needs the `devx` profile (`make up` or `make devx-up`).

- **Metrics.** The api serves `/metrics` on its own port, the worker on
  `TADAS_METRICS_PORT` (9464). Prometheus scrapes both, as containers
  (`api:8000`, `maintenance:9464`) and as host processes
  (`host.docker.internal:8000` and `:9464`); whichever is not running shows
  as down on http://localhost:59090/targets, which is expected. Grafana
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
  log lines become issues, tagged with `service`, `release`, and
  `request_id`. An empty or `off` DSN turns reporting off.

## When something is off

| Symptom | Likely cause and fix |
|---------|----------------------|
| `postgres` exits right after start | A volume from another Postgres major version. `make reset`, or reset only the database as above. |
| `api` exits at start with `Failed connecting to valkey` | Valkey was not reachable yet as the API booted. `dc up -d --wait api`. |
| `port is already allocated` | Another process holds that host port: `lsof -nP -iTCP:<port> -sTCP:LISTEN`. For a dashboard, set its `TADAS_<DASHBOARD>_PORT` in `.env`. |
| The portal loads but every request fails | The API is down, or the portal was built for another `VITE_API_URL`: `dc ps api`, then rebuild the portal. |
| The API refuses to start, naming a setting | `.env` predates a rename; compare it with `.env.example`. |
| `scripts/dev.sh` fails on port 8000 | The `api` container is running: `dc stop api maintenance portal`. |
