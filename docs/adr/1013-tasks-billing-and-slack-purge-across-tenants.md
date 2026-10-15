# ADR 1013: Tasks, billing, and Slack purge across tenants

**Status**: accepted (2026-10-14)

## Context

[ADR 0045, Retention purges run once a pass across tenants](0045-retention-purges-run-once-a-pass-across-tenants.md)
has each namespace purge its rows past their retention in one named
storage method across tenants, and keeps per tenant only the purge of a
tenant deleted longer ago than the retention. Tadas's namespaces hold
rows of both kinds. A deleted task, a billing delivery's mark, and a
Slack install state, post, or removed installation each carry a
retention. An open or a done task, the billing account, and a live
installation carry none.

## Decision

- **Tasks** go across tenants, with one tenant-shaped part. The read of
  deleted tasks is one statement a pass, on `(deleted_at)`. A deleted
  task's attachments are still detached first, under its tenant's
  service context, because that write lands an outbox row with its
  actor. Only a tenant with such a task pays for it. The context is the
  one the pass minted, deleted tenants included, from `sweep_context`.
  A tenant marked purged has none: its files went with it, so its tasks
  go as they are.
- **Billing**: the delivery marks past the retention, one statement.
- **Slack**: removed installations, expired or redeemed install states,
  and posts past the retention, a statement each, in one transaction,
  since the three tables are one role's.

The purge of a tenant past its retention takes the rows that carry no
retention of their own: its tasks, its billing account and marks, and
its Slack rows.

## Consequences

A living tenant still costs a pass no purge. A deleted task whose files
will not go stays for the next pass, and is counted under the
`tasks` subsystem as `detach_failed`.
