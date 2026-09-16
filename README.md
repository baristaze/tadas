# Tadas

A multi-tenant to-do application for teams of people and the programs
that work alongside them. The system is built in the shape the Software
Design and Architecture Guidelines prescribe: one object model library
at the center (`om/`), one infrastructure toolkit (`infra/`), services
and workers around them, and apps at the edge.

## Set up

Requirements: uv, pnpm, Docker.

```bash
make setup        # Python and TypeScript dependencies
cp .env.example .env
make infra-up     # Postgres, Redis, ElasticMQ, MinIO on host ports 55432, 56379, 59324, 59000
make migrate      # every role's migration chain
```

## Run

```bash
scripts/dev.sh    # every application process on the host
```

## Check

```bash
make check             # lint, format, types, unit tests (the fast gate)
make migrate-check     # every role's ORM metadata against the migrated schema
make test-integration  # the same storage contracts over Postgres, plus migrations
```

## Layout

- `om/` the object model: entities, managers, storage, migrations
- `infra/` cache, buckets, topics, queues, secrets, observability
- `services/` web services; `workers/` background roles; `apps/` clients
- `clients/` typed clients, one per service; `deployment/` compose, images, Terraform
- `docs/` as built, ADRs, runbooks; `scripts/` dev.sh and the cloud migration runner
