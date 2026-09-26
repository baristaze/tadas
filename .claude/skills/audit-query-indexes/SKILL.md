---
name: audit-query-indexes
description: "Audit whether the indexes fit the queries, and what breaks first under load: every statement the Postgres storage sends, mapped to the index that serves it and measured with EXPLAIN on a database of its own seeded at a stated scale, under the login and the tenant scope the application uses. Reports each statement's verdict, the hot paths, the unused indexes, and fixes tested on the same data. Never changes anything."
allowed-tools: Read, Grep, Glob, Write, Bash(uv run:*), Bash(git:*)
---

# audit-query-indexes

Every query the platform sends, the index that serves it, and what it
costs when the data is large. The costs are measured, not guessed: on a
database the run makes and seeds, under the same login, row-level
security policy, and scope the storage funnel uses.

## Input

`[--scale <n>] [--ref <git ref>] [--focus <namespace,...>]`

`--scale` is the seed's, `1` by default (5,000 people, a team org of
100,000 tasks, a million events, 50,000 work items); `0.01` is a quick
run with the same shape, whose times prove the wiring and nothing about
scale. `--ref` is the code audited, `origin/main` by default. `--focus`
narrows the audit to some namespaces (`tasks`, `events`, `work`, ...);
every namespace by default.

## Role and credential

Investigator, local only. The skill runs on the local stack (`make
infra-up`, with `make migrate` run once), in a database it makes, seeds,
and drops. It holds no cloud credential and reads no environment.

## Procedure

1. Name the run: `audit_query_indexes_<yyyymmdd>`, the date of today.
   Make the evidence folder `~/Downloads/tadas_query_indexes_<yyyy-mm-dd>/`.
   Read `--ref` with `git show <ref>:<path>` when it is not the checkout's
   own commit; say which commit the report read.
2. List every statement. The storage impls are
   `om/src/tadas/om/<namespace>/storage/impl/postgres.py`; the indexes
   are in the table classes (`om/src/tadas/om/*/storage/tables/*.py`) and
   the migrations (`om/migrations/sql/<role>/`, newest last). For each
   statement note its caller and how often it runs: every request, every
   write, every creating POST, once per sweep pass per tenant, once per
   pass, or rare. The callers are the managers
   (`om/src/tadas/om/*/impl/`), the routes
   (`services/api/src/tadas/services/api/routes/`), and the worker
   (`workers/maintenance/src/tadas/workers/maintenance/`).
3. Make and seed the run's database:

   ```bash
   uv run python ops/audit/auditdb.py create audit_query_indexes_<yyyymmdd>
   uv run python ops/audit/seed.py audit_query_indexes_<yyyymmdd> --scale <scale>
   uv run python ops/audit/explain.py reset audit_query_indexes_<yyyymmdd>
   ```

4. Measure every statement. Write them into
   `~/Downloads/tadas_query_indexes_<yyyy-mm-dd>/statements.sql` in the
   format and with the cases `${CLAUDE_SKILL_DIR}/statements.md` gives
   (read it before writing the file), then run:

   ```bash
   uv run python ops/audit/explain.py plans audit_query_indexes_<yyyymmdd> ~/Downloads/tadas_query_indexes_<yyyy-mm-dd>/statements.sql > ~/Downloads/tadas_query_indexes_<yyyy-mm-dd>/plans.txt
   ```

   A verdict per statement: `fine` (an index condition that stops at the
   page or the key), `risk` (linear in something that grows, but fine
   today), `gap` (reads far more than it returns where it runs often).
5. The hot paths. For each of the per-request baseline, the task lists,
   the event append, the queue claim, the outbox relay, and the sweep's
   pass, say what it costs and what grows it, from the plans and from the
   frequency of step 2. A per-tenant cost times the number of tenants is
   the sweep's; a lock held across round trips (the event cursor) caps a
   tenant's write rate. Contention is measured only when `--focus` asks
   for it, with the storage impls as `${CLAUDE_SKILL_DIR}/statements.md`
   shows.
6. Test each fix on the same data before proposing it. Create the
   candidate index on the run's database, measure the statements it
   serves again from a file of their own, and drop it before the next
   candidate, so each after is measured against the migrations' indexes
   plus that one:

   ```bash
   uv run python ops/audit/explain.py index audit_query_indexes_<yyyymmdd> "CREATE INDEX ix_try ON core.tasks (org_id, assignee_id, status) WHERE deleted_at IS NULL"
   uv run python ops/audit/explain.py plans audit_query_indexes_<yyyymmdd> ~/Downloads/tadas_query_indexes_<yyyy-mm-dd>/try_<n>.sql
   uv run python ops/audit/explain.py index audit_query_indexes_<yyyymmdd> "DROP INDEX core.ix_try"
   ```

   Say the before and the after, and whether the generic plan picks the
   index too (a partial index whose predicate names a bound value is
   one a generic plan cannot use).
7. Read the inventory: an index with no scans after step 4 serves no
   statement the audit measured; weigh it against the writes it costs.

   ```bash
   uv run python ops/audit/explain.py inventory audit_query_indexes_<yyyymmdd> > ~/Downloads/tadas_query_indexes_<yyyy-mm-dd>/inventory.md
   ```

8. Drop the run's database, whatever happened before:

   ```bash
   uv run python ops/audit/auditdb.py drop audit_query_indexes_<yyyymmdd>
   ```

9. Write the report, and the proposed tickets in it. The skill files
   none.

## What it never does

- Never writes to a shared database or to an environment: it logs in
  only to the database it made on the local stack, and drops it.
- Never modifies a tracked file, never commits, never opens a pull
  request: a tested index is a proposal with its numbers, not a
  migration.
- Never reports a time from a scale it did not seed as measured: a larger
  scale is an extrapolation, and the report says so.

## Output

`~/Downloads/tadas_query_indexes_<yyyy-mm-dd>.md`:

```markdown
# Tadas: query patterns, indexes, and load

Scope: <commit>. Seed: scale <n> (<the counts seed.py printed>). Postgres <version>, local.

## The answer

<one paragraph: mostly fine or not, the gaps by place, the top three by impact>

## How it was measured

## Every query

### <namespace> (`<storage impl path>`)

| Table | Query shape | Caller, frequency | Index | Measured | Verdict |
|---|---|---|---|---|---|

## Hot paths and contention

## Recommendations, by impact

1. **<fix>.** Evidence: <before → after, on this seed>. Change: <SQL>.
   Effort S/M/L. Needed: <now, or at what scale>. Proposed ticket: <title>.

## Redundant or unused indexes

## What I could not verify
```
