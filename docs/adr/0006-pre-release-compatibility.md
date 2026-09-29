# ADR 0006: Renames under `/v1` and one-step migrations until the first deployment

**Status**: accepted (2026-09-18), amended (2026-09-29). The migration
half ended with the first deployment, staging's, on 2026-09-22. The last
rename in one migration, `202609202100_operator_role`, came before it,
and a column has moved in two releases since
([ADR 0038](0038-a-dead-column-leaves-the-mapping-before-the-table.md),
[ADR 0050](0050-a-move-writes-one-row.md)). The wire half is still open.
Since that day a field has left `/v1` one release after it was marked
deprecated, where NET-23 asks for `/v2`: a task write's `version`
([ADR 0009](0009-tasks-carry-a-version.md)), then `remind_at`
([ADR 0034](0034-a-task-is-due-on-a-date.md)), and `position` next
([ADR 0050](0050-a-move-writes-one-row.md)).

## Context

The guideline (v0.4.0, Public Types and Migrations) says a view inside
`/v1` only gains fields and a rename is a new prefix, and that a
migration is compatible with the release before it because a rollout
runs both at once (expand and contract). Adopting v0.4.0 renames
`EventView` (`entity`, `entity_id`, `action` become `kind`,
`target_id`), the socket's `EntityChangedView` with it, and the columns
behind them (`events.entity` to `kind`, `work_items.queue` to `lane`),
each in one step.

## Decision

Until the first environment is deployed (the deploy workflow skips the
cloud while its variables are empty), a rename lands under `/v1` and a
migration renames in one step. The API's only consumer is the portal in
this repository and the version is 0.1.0; there is no release to run
beside. From the first deployment on, both rules apply as written: a
removal or a rename is `/v2`, and a column moves by add, backfill,
switch, drop across releases.

## Consequences

Reviews treat the `EventView` shape and the two rename migrations as
the recorded exceptions, not as the pattern. The next incompatible wire
change opens `/v2`; the next column rename ships as two migrations in
two releases.
