---
name: audit-database-calls
description: "Audit how many database calls each endpoint and each worker flow makes, at its least and at its most: round trips, transactions, and roles, counted at the driver while the real API and worker run in one process over a database of their own. Names what grows a flow, every N+1, every read repeated within a flow, and the fixed cost of a transaction, each with its fix and effort. Never changes anything."
allowed-tools: Read, Grep, Glob, Write, Bash(uv run:*), Bash(git:*), Bash(mkdir:*)
---

# audit-database-calls

For every route and every worker flow: how many round trips it sends to
the database, in how many transactions, on which roles, at its least and
at its most, and what makes the most grow. The count is taken at the
driver while the real API and worker run in one process, so it is what
the code does, not what it looks like it does.

## Input

`[--only <flow,...>]`

The audit counts the checkout, tools and code alike; to count another
commit, run it from a checkout of that commit that has `ops/audit/`.
Every command runs from the repository root. `--only` runs some of the
built-in flows (`auth`, `tenancy`, `tasks`, `attachments`, `events`, `billing`,
`worker`, `sweep`, `health`); `seed` always runs first, and a flows
file of the run's own always runs in full.

## Role and credential

Investigator, local only. The skill runs on the local stack (`make
infra-up`, with `make migrate` run once), in a database it makes and
drops, with the provider twins (identity, payments, Slack) in place of
the providers. It holds no cloud credential and reads no environment.

## Procedure

1. Name the run: `audit_database_calls_<yyyymmdd>`, today's date in UTC.
   When `uv run python ops/audit/auditdb.py list` shows that name taken,
   another run holds it: add a suffix (`_2`), and never drop a database
   this run did not make. Make the evidence folder
   `~/Downloads/tadas_database_calls_<yyyy-mm-dd>/` (`mkdir -p`). Say
   which commit the run counted (`git rev-parse HEAD`).
2. List every route (the routers under
   `services/api/src/tadas/services/api/routers/`, the socket in
   `.../api/realtime/socket.py`, and `/healthz`, `/readyz`, and `/metrics`
   in `.../api/app.py`), every kind of work item (`WorkKind` in
   `om/src/tadas/om/work/types/work_item.py`) and its handler and every
   consumer (`workers/maintenance/src/tadas/workers/maintenance/`), and
   the sweep's steps (that folder's `loop.py`, `_sweep_once`). Compare the list with the calls the built-in flows make
   (`ops/audit/dbcalls_flows.py`): a route or a flow they do not reach is
   written into a flows file of the run's own, as
   `${CLAUDE_SKILL_DIR}/references/flows.md` shows (read it before writing one).
   Add a second call wherever a size changes the count: one id and a
   hundred, an org of one and of many, a list of one row and a full page.
   A route that needs a provider's setup the twins cannot give in a flow
   is listed under "What I could not measure", with why.
3. Make the database and count:

   ```bash
   uv run python ops/audit/auditdb.py create audit_database_calls_<yyyymmdd>
   uv run python ops/audit/dbcalls.py run audit_database_calls_<yyyymmdd> \
     --out ~/Downloads/tadas_database_calls_<yyyy-mm-dd>/calls.json \
     [--flows ~/Downloads/tadas_database_calls_<yyyy-mm-dd>/more_flows.py] [--only <flows>]
   uv run python ops/audit/dbcalls.py summary ~/Downloads/tadas_database_calls_<yyyy-mm-dd>/calls.json
   ```

   A flow that fails is named, the rest run, and `run` exits 1; go on to
   the summary and the drop all the same. Fix a failed flow in the run's
   flows file and run the file alone on the same database with `--only
   seed` into a second `--out` (`calls_2.json`), or report it as not
   measured. The summary's round trips are warm (every statement already
   prepared); the report uses them and says so, and `calls.json` holds
   each call's `prepares` beside them. Tally `calls.json` with a scratch
   script (`uv run python <script>`), never a file in the repository.
4. Read each call's `detail` in `calls.json`: one line per transaction,
   with its role, its scope, the storage method that opened it, and its
   statements. From them, per route and flow:
   - the fixed cost: every transaction pays `BEGIN`, the scope's
     `set_config`, and `COMMIT` or `ROLLBACK`, so a one-statement read is
     four round trips;
   - the per-request baseline of each credential (session, API key,
     sign-in credential, operator token), and each route's cost above it;
   - what grows it: a count that rises with a list, an id set, the
     orgs of a person, the members of an org; say the formula (`13 + 8M`)
     and the sizes it was measured at;
   - an N+1 (a transaction per row), a read repeated within one flow, a
     transaction opened and rolled back with nothing in it, several
     transactions in a row on the same role that one would serve.
5. Drop the run's database, whatever happened before, and check it is
   gone:

   ```bash
   uv run python ops/audit/auditdb.py drop audit_database_calls_<yyyymmdd>
   uv run python ops/audit/auditdb.py list
   ```

6. Write the report, and the proposed tickets in it. The skill files
   none.

## What it never does

- Never writes to a shared database or to an environment: it logs in
  only to the database it made on the local stack, and drops it.
- Never modifies a tracked file, never commits, never opens a pull
  request: a run's own flows live in its evidence folder, and a fix is a
  proposal with its numbers.
- Never calls a real provider: the twins stand in for every one.
- Never gives a maximum it did not measure as measured: a formula from the
  code is marked as one, with the sizes that agree with it.

## Output

`~/Downloads/tadas_database_calls_<yyyy-mm-dd>.md`:

```markdown
# Tadas: database calls per endpoint and flow

<commit>, counted on <database>, with the provider twins. How the count is taken, in two sentences.

## How to read the numbers

## Short answer

- Baseline per authenticated request: <n> round trips, <n> transactions.
- The cheapest and the most expensive routes and flows, with their counts.
- What grows with data.
- Surprises.

## Per-request baseline

| Credential | Round trips | Transactions | Roles | What it reads |

## Tables per area

| Flow | Min | Max (or formula) | Transactions | Roles | What drives the range | Measured |

Measured: yes, formula, or read (code only).

## Findings, by impact

1. **<finding>.** Where (file:line). The waste (numbers). The fix. Effort
   S/M/L. Proposed ticket: <title>.

## What I could not measure
```
