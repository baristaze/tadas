# ADR 1015: A create reads its plan's count and its place in one transaction

**Status**: accepted (2026-10-14)

## Context

[ADR 0053, The scope rides in the message that begins](0053-the-scope-rides-in-the-message-that-begins.md)
sends the scope in the message that begins each transaction, and keeps
the reads of one namespace on one role in one transaction, in a storage
method of their own. Under a plan with a bound on active tasks, Tadas's
task create reads two things of the tasks table: the count the bound is
held to, and the top place the new task takes.

## Decision

`count_open_and_read_places` reads both in one transaction. With no
bound, the place alone is read.

A create still reads the plan, the top place, and the Slack
installation in three transactions, and `GET /v1/billing` makes four
reads. Each is a namespace of its own, and folding them is a decision
about STO-02, not about the scope.

## Consequences

Across the database-call harness (`ops/audit/dbcalls.py`), Tadas's
flows cost 11,504 round trips where the scope as a statement of its own
costs 14,734 (22 % fewer), with the same 3,230 transactions:

| Flow | Round trips, a statement of its own → with `BEGIN` | Transactions |
|---|---|---|
| A plain authenticated read (`GET /v1/tasks/{id}`) | 14 → 11 | 3 → 3 |
| `POST /v1/tasks` | 35 → 27 | 8 → 8 |
| `POST /v1/tasks` on Free | 40 → 31 | 9 → 9 |
| `GET /v1/billing` | 26 → 20 | 6 → 6 |
| `GET /v1/admin/size` | 24 → 18 | 6 → 6 |
| `GET /v1/change-events` | 15 → 12 | 3 → 3 |
