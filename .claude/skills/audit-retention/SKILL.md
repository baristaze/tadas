---
name: audit-retention
description: "Audit which stores grow without bound and what trims them: every table of every role, with what writes it, when a row is stale, the purge that deletes it, its retention, and whether that purge is batched and indexed; then the stores outside the database (log groups, buckets, queues, the cache). Measures the purges on a database of its own, reads staging's retention settings read-only, and writes a report with verdicts and proposed tickets. Never changes anything."
allowed-tools: Read, Grep, Glob, Write, Bash(uv run:*), Bash(git:*), Bash(aws:*)
---

# audit-retention

Which tables grow for ever, which purge trims each one, and whether that
purge still works when the table is large. The answer comes from the code,
checked against plans on a seeded database of the run's own, and against
the retention settings staging actually runs with.

Read `.claude/skills/_shared/ops-preamble.md` before the first step: the
profiles, the account check, and the env file are there.

## Input

`[--env local|staging] [--scale <n>] [--ref <git ref>]`

`--env` is where the stores outside the database are read: `staging` by
default, `local` to read none and say so. `--scale` is the seed's, `1`
by default (5,000 people, a team org of 100,000 tasks, a million
events); `0.01` is a quick run with the same shape. `--ref` is the code
audited, `origin/main` by default.

## Role and credential

Investigator, read-only. The database half runs on the local stack
(`make infra-up`, with `make migrate` run once), in a database the run
makes, seeds, and drops; it holds no cloud credential. The staging half
runs under `tadas-staging-investigate`, checked with `sts
get-caller-identity` before any other `aws` command, as the preamble
states. Refuse any profile wider than the investigate role. Every `aws`
command carries `--profile tadas-staging-investigate`. The skill reads no
env file and no token: it calls no route.

## Procedure

1. Name the run: `audit_retention_<yyyymmdd>`, the date of today. Make
   the evidence folder `~/Downloads/tadas_retention_<yyyy-mm-dd>/`. Check
   out nothing: read `--ref` with `git show <ref>:<path>` when it is not
   the checkout's own commit, and say which commit the report read.
2. List every table. The migrations are the truth
   (`om/migrations/sql/<role>/*.up.sql`, newest last); the table classes
   are `om/src/tadas/om/*/storage/tables/*.py`. A table a later migration
   drops is not live. For each live table find: what writes it (the
   storage impl's inserts, `om/src/tadas/om/*/storage/impl/postgres.py`),
   what it grows with, and when a row is stale.
3. Find the purge of each table. The sweep is
   `workers/maintenance/src/tadas/workers/maintenance/loop.py`
   (`_sweep_once`); the per-tenant purges and the purges across tenants
   are the two maps in `workers/maintenance/src/tadas/workers/maintenance/main.py`;
   each calls a manager's `purge_*`, which calls its storage's delete.
   The retention of each is a setting in
   `workers/maintenance/src/tadas/workers/maintenance/settings.py`
   (`TADAS_*_RETENTION_*`), passed into the manager's options in
   `container.py`. For each purge note: its statement, whether it deletes
   a batch (`delete_batch`, `LIMIT`) or everything at once, and which
   index serves its `WHERE`. A table no purge reaches is a gap unless it
   is kept on purpose (the org row, the record); say which.
4. Measure the purges. Make and seed the run's database:

   ```bash
   uv run python ops/audit/auditdb.py create audit_retention_<yyyymmdd>
   uv run python ops/audit/seed.py audit_retention_<yyyymmdd> --scale <scale>
   uv run python ops/audit/explain.py reset audit_retention_<yyyymmdd>
   ```

   Write each purge's statement into
   `~/Downloads/tadas_retention_<yyyy-mm-dd>/purges.sql`, in the file
   format `${CLAUDE_SKILL_DIR}/purges.md` gives (read it before writing
   the file), with the cut-offs the settings give, and run:

   ```bash
   uv run python ops/audit/explain.py plans audit_retention_<yyyymmdd> ~/Downloads/tadas_retention_<yyyy-mm-dd>/purges.sql
   uv run python ops/audit/explain.py inventory audit_retention_<yyyymmdd>
   ```

   A plan with a `Seq Scan` on a large table, or rows read far beyond the
   rows deleted, is a finding with its numbers. Each plan runs in a
   transaction that is rolled back, so nothing is deleted.
5. The stores outside the database. The Terraform modules under
   `deployment/terraform/modules/` state each one's retention: log groups
   (`log_retention_days`), buckets' lifecycle rules, queues'
   `message_retention_seconds`, and the cache's TTLs
   (`infra/src/tadas/infra/cache/`). With `--env staging`, check what is
   live, read-only:

   ```bash
   aws logs describe-log-groups --log-group-name-prefix /tadas/staging --profile tadas-staging-investigate
   aws logs describe-log-groups --log-group-name-prefix /aws/ecs --profile tadas-staging-investigate
   aws sqs list-queues --queue-name-prefix tadas-staging --profile tadas-staging-investigate
   aws sqs get-queue-attributes --queue-url <url> --attribute-names MessageRetentionPeriod --profile tadas-staging-investigate
   aws s3api list-buckets --profile tadas-staging-investigate
   aws s3api get-bucket-lifecycle-configuration --bucket <name> --profile tadas-staging-investigate
   ```

   A log group with no `retentionInDays` is a finding. The database's
   size in staging is `FreeStorageSpace` in `AWS/RDS`
   (`aws cloudwatch get-metric-statistics`), since no role logs in to it.
6. Drop the run's database, whatever happened before:

   ```bash
   uv run python ops/audit/auditdb.py drop audit_retention_<yyyymmdd>
   ```

7. Write the report, and the proposed tickets in it. Each ticket names
   the table, the evidence, the fix, and the effort. The skill files
   none.

## What it never does

- Never writes to a shared database or to an environment: it logs in
  only to the database it made on the local stack, and drops it.
- Never modifies a tracked file, never commits, never opens a pull
  request: it writes a report and proposes tickets.
- No `aws` verb that is not `describe`, `get`, or `list`; no secret read.
- No row count from staging: no role reads its rows, and the report says
  so rather than guessing.

## Output

`~/Downloads/tadas_retention_<yyyy-mm-dd>.md`:

```markdown
# Tadas: which stores grow for ever, and what trims them

Read at <commit>; seeded at scale <n>; stores read in <env> under <profile and Arn>.

## The answer

<two paragraphs: what is trimmed, the gaps, the risks, most important first>

## Every table

| table | what writes it | grows with | stale when | trimmed by (file:line) | retention | batched / indexed | verdict |
|---|---|---|---|---|---|---|---|

Verdicts: fine, risk, gap, kept on purpose.

## Findings, by impact

### <gap or risk>: <table>
**What.** **The harm.** **Evidence** (plan, rows read, file:line).
**Fix.** **Effort** S/M/L. **Proposed ticket:** <title>.

## Stores outside the database

| store | retention | verdict |

## What I could not verify
```
