# Local stack

Two compose files and one profile make up everything that runs locally.
Every command below runs from the repository root.

| File or profile | Adds |
|-----------------|------|
| `docker-compose.yml` | Postgres, Valkey, ElasticMQ, MinIO |
| `docker-compose.full.yml` | the `api`, `maintenance`, and `portal` containers, built from the working tree |
| profile `devx` (in `docker-compose.yml`) | pgweb, Valkey Admin, ElasticMQ UI, Jaeger |

The compose project is `tadas`, so containers are named `tadas-<service>-1`
and the volumes `tadas_postgres` and `tadas_minio`.

## URLs and ports

Everything listens on 127.0.0.1 only. `make urls` prints the browser URLs.

| Service | From the host | Inside the compose network | Sign-in |
|---------|---------------|----------------------------|---------|
| portal | http://localhost:55173 | `portal:8080` | `owner@example.test` / `tadas-local` (after `make seed`) |
| api | http://127.0.0.1:8000 (`/docs`, `/metrics`, `/healthz`) | `api:8000` | |
| postgres | `127.0.0.1:55432` | `postgres:5432` | `tadas` / `tadas`, database `tadas` |
| valkey | `127.0.0.1:56379` | `valkey:6379` | none: user `default`, no password |
| elasticmq (SQS) | http://127.0.0.1:59324 | `elasticmq:9324` | any key |
| minio (S3) | http://127.0.0.1:59000 | `minio:9000` | `tadas` / `tadastadas` |
| MinIO console | http://localhost:59001 | | `tadas` / `tadastadas` |
| pgweb (devx) | http://localhost:58081 | | none |
| Valkey Admin (devx) | http://localhost:58080 | | none; see below |
| ElasticMQ UI (devx) | http://localhost:53000 | | none |
| Jaeger UI (devx) | http://localhost:56686 | | none |
| Jaeger OTLP (devx) | http://127.0.0.1:54318 | `jaeger:4318` | none |

`maintenance` has no port; its healthcheck reads its liveness key in Valkey.

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
| Start only the dashboards | `dc up -d pgweb valkey-admin elasticmq-ui jaeger` |
| Stop only the dashboards | `dc stop pgweb valkey-admin elasticmq-ui jaeger` |
| Apply new migrations | `make migrate` |
| Seed again, or as someone else | `make seed SEED_EMAIL=me@example.test SEED_PASSWORD=secret SEED_SLUG=mine` |

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

## Traces

Jaeger receives traces only from processes that export them. For host
processes (`scripts/dev.sh`), set `TADAS_OTEL_ENDPOINT=http://127.0.0.1:54318`
in `.env` and restart them. The app containers read their settings from
`docker-compose.full.yml`, which sets no endpoint; add
`TADAS_OTEL_ENDPOINT: http://jaeger:4318` to its `x-app-env` block to trace
them too.

## When something is off

| Symptom | Likely cause and fix |
|---------|----------------------|
| `postgres` exits right after start | A volume from another Postgres major version. `make reset`, or reset only the database as above. |
| `api` exits at start with `Failed connecting to valkey` | Valkey was not reachable yet as the API booted. `dc up -d --wait api`. |
| `port is already allocated` | Another process holds that host port: `lsof -nP -iTCP:<port> -sTCP:LISTEN`. |
| The portal loads but every request fails | The API is down, or the portal was built for another `VITE_API_URL`: `dc ps api`, then rebuild the portal. |
| The API refuses to start, naming a setting | `.env` predates a rename; compare it with `.env.example`. |
| `scripts/dev.sh` fails on port 8000 | The `api` container is running: `dc stop api maintenance portal`. |
