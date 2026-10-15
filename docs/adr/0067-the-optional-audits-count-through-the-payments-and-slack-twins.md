# ADR 0067: The optional audits count through the payments and Slack twins

**Status**: accepted (2026-09-26)

## Context

[ADR 0080, The optional audits count as well as read](0080-the-optional-audits-count-as-well-as-read.md)
has `audit-credential-lifetimes` and `audit-provider-calls` count on
the local stack, with the identity provider's twin in place of the
provider. Tadas's flows call two more providers, Stripe and Slack, and
each has a twin of its own in `integrations`.

## Decision

The audits count through every provider's twin: identity, payments,
and Slack. `ops/audit/dbcalls.py` runs the API and the worker with the
payments and Slack backends set to their twins, and records each call a
flow makes to the three twins, in order (`dbcalls.py providers` lists
them). The audits still call no real provider, Stripe and Slack
included.

## Consequences

- A flow that calls Stripe or Slack is measured, not read, in both
  audits' reports.
- A new provider's flows are measured once it has a twin and the audit
  run sets its backend to it.
