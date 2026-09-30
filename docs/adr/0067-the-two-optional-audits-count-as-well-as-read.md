# ADR 0067: The two optional audits count as well as read

**Status**: accepted (2026-09-26)

## Context

OPS-11 (Operations, Operational Skills) names the built-in skills: the
operational skills, four audits, and two optional audits,
`audit-credential-lifetimes` and `audit-provider-calls`. Of the two
optional ones it says: "Both read the code and the settings, and
nothing else."

A reading gives an estimate of what a check or a call costs. A count
gives the fact, and `audit-database-calls` already counts at the
driver, on a database the run makes and drops.

## Decision

**The two optional audits count as well as read.**
`audit-credential-lifetimes` and `audit-provider-calls` read the code
and the settings. They also count what a check or a call costs, through
the provider twins, on a database the run makes and drops, as
`audit-database-calls` does. Each still holds no credential, reads no
environment, calls no real provider, and writes to no shared database.
A count is a fact where a reading is an estimate, and each row of the
report says which it is.

This is a deviation from OPS-11.

## Consequences

- A review that reads OPS-11 on the two optional audits cites this
  record.
- Each of the two needs the local stack up, where a reading alone
  needs nothing.
