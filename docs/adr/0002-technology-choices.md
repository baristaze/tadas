# ADR 0002: Technology choices as adopted

Date: 2026-09-16

## Context

The guideline names technologies as defaults and asks a project to
record, once, every technology it uses and every substitution it makes.

## Decision

Tadas adopts every technology the guideline names, with the one
substitution recorded below the table:

| Choice in the guideline               | Adopted                         |
|---------------------------------------|---------------------------------|
| Object model language and validation  | Python 3.14, Pydantic 2         |
| Relational store, ORM, migration runner | Postgres 18, SQLAlchemy 2 (asyncpg), Alembic (runner only) |
| Cache                                 | Valkey 9.1 (substitutes Redis; ElastiCache in the cloud), GLIDE client |
| Object store                          | S3 (MinIO locally)              |
| Inbound queue                         | SQS (ElasticMQ locally)         |
| Topic bus                             | Valkey pub/sub (substitutes Redis; in-process dispatcher in tests) |
| Secret store                          | AWS Secrets Manager (env and file locally) |
| Browser apps                          | React, TypeScript, Vite, TanStack Query, Zustand |
| Workspaces                            | uv, pnpm                        |
| Local stack                           | Docker Compose                  |
| Cloud and infrastructure as code      | AWS, Terraform                  |
| Traces and metrics                    | OpenTelemetry, Prometheus client |
| Logging                               | Python `logging`                |

Substitutions. Each row names the choice, the substitute, the reason, and
the rules the substitute must still satisfy (a queue claim that skips
locked rows or a compare-and-set, an atomic cache increment,
at-least-once topic delivery to every subscribed process).

| Choice | Substitute | Reason | Rules it still satisfies |
|--------|------------|--------|--------------------------|
| Redis (cache, topic bus) | Valkey 9.1, with the Valkey GLIDE client | ElastiCache offers no Redis OSS past 7.1; Valkey is its current engine, protocol-compatible, and open source (BSD). Locally the same image runs, so local and cloud match. | `INCR` is atomic; `PSUBSCRIBE` delivers every publish to every subscribed process, as with Redis |

## Consequences

Reviews treat the names above as the guideline's names. A change of
shape, not of name, is a deviation and is recorded separately.
