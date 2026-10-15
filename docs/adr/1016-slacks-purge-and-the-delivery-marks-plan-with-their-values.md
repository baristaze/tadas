# ADR 1016: Slack's purge and the delivery marks plan with their values

**Status**: accepted (2026-10-14)

## Context

[ADR 0056, Purges across tenants plan with their values](0056-purges-across-tenants-plan-with-their-values.md)
found the scaffold's purges keeping a sequential scan after a backlog,
measured through the driver on a seed of 5,000 tenants. Measured the
same way, Tadas's own purges:

| Purge | Idle plan the connection keeps | Idle execution |
|---|---|---|
| Slack install states (20,000) | Seq Scan | 0.83 ms |
| billing delivery marks, Slack posts | generic, still on their indexes | under 0.07 ms |
| deleted tasks, Slack installations | custom | under 0.05 ms |

## Decision

**Slack's transaction and the delivery marks plan with their values.**
`PLAN_WITH_VALUES` is the first statement of the Slack purge's one
transaction (installations, install states, posts) and of the billing
delivery marks' purge.

**The read of deleted tasks keeps its order by `deleted_at`.** Its
partial index, `ix_tasks_deleted_at`, holds deleted rows alone, so an
index walk in that order reads only rows the purge may take, and stops
at the limit.

## Consequences

`test_the_invitations_and_slack_purges_read_their_indexes`, in
`om/tests/integration/test_hot_reads_postgres.py`, holds that the Slack
purges read their indexes.
