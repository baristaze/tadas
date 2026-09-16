# ADR 0002: Technology choices as adopted

Date: 2026-09-16

## Context

The guideline names technologies as defaults and asks a project to
record, once, every technology it uses and every substitution it makes.

## Decision

Tadas adopts every technology the guideline names, with no
substitutions:

| Choice in the guideline               | Adopted                         |
|---------------------------------------|---------------------------------|
| Object model language and validation  | Python 3.13, Pydantic 2         |
| Relational store, ORM, migration runner | Postgres 16, SQLAlchemy 2 (asyncpg), Alembic (runner only) |
| Cache                                 | Redis (a hosted Redis in the cloud) |
| Object store                          | S3 (MinIO locally)              |
| Inbound queue                         | SQS (ElasticMQ locally)         |
| Topic bus                             | Redis pub/sub (in-process dispatcher in tests) |
| Secret store                          | AWS Secrets Manager (env and file locally) |
| Browser apps                          | React, TypeScript, Vite, TanStack Query, Zustand |
| Workspaces                            | uv, pnpm                        |
| Local stack                           | Docker Compose                  |
| Cloud and infrastructure as code      | AWS, Terraform                  |
| Traces and metrics                    | OpenTelemetry, Prometheus client |
| Logging                               | Python `logging`                |

Substitutions: none. When one is made, add a row here naming the
choice, the substitute, the reason, and the rules the substitute must
still satisfy (a queue claim that skips locked rows or a
compare-and-set, an atomic cache increment, at-least-once topic
delivery to every subscribed process).

## Consequences

Reviews treat the names above as the guideline's names. A change of
shape, not of name, is a deviation and is recorded separately.
